# MIT License
# 
# Copyright (c) 2025 REY Alice, HAJ HAMOUDA Jihene, HENI Yahia,
# ALAOUI Mohamed Mehdi, MHADHBI Kaies
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

''' This Python script processes OpenStreetMap (OSM) data to analyze roads,
buildings, and trees to calculate the shade percentage of buildings 
and trees on roads based on solar position. It uses osmium to parse OSM 
data.'''

import osmium
from pvlib import solarposition
from shapely.geometry import LineString, Polygon, Point
from pyproj import CRS, Transformer
from shapely.ops import transform, unary_union
from shapely.affinity import translate
import numpy as np
import cProfile
import pstats
import pandas as pd
from rtree import index
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from functools import lru_cache

if __name__ == "__main__":
    start_time = time.time()  # Start measuring time
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Define coordinate systems
    crs_latlon = CRS("EPSG:4326")  # WGS84 (latitude/longitude)
    crs_projected = CRS("EPSG:32630")  # UTM for meter-based projection
    transformer_to_meters = Transformer.from_crs(crs_latlon, crs_projected, always_xy=True)

    class WayModifier(osmium.SimpleHandler):
        def __init__(self, input_file, output_pbf, max_workers=4):
            super().__init__()
            # Fixed parameters
            self.road_width = 10  # Average road width
            self.building_area_spread = 50  # Radius to get buildings around roads
            self.default_building_height = 4  # Default building height (meters)
            self.level_height = 2.8  # Average height per floor (meters)
            self.tree_area_spread = 20  # Radius to get trees around roads
            self.default_tree_height = 5  # Default tree height (meters)
            self.default_tree_width = 3  # Default tree width (meters)
            
            # Setup
            self.transformer_to_meters = transformer_to_meters
            self.input_file = input_file
            self.pbf_writer = osmium.SimpleWriter(output_pbf)
            self.modified = False
            self.max_workers = max_workers
            
            # Get current time once for all calculations
            self.time = pd.DatetimeIndex([pd.Timestamp.now().tz_localize("Europe/Paris")])
            
            # Load data
            self.buildings, self.trees, self.center = self.get_data(input_file)
            
            # Prepare spatial indices
            self.build_spatial_indices()
            
            # Create default tree shadow (reused for each tree)
            self.x_default_tree, self.y_default_tree = 0, 0
            if self.center:
                center_meters = transform(transformer_to_meters.transform, self.center)
                self.x_default_tree, self.y_default_tree = center_meters.x, center_meters.y
            
            # Pre-calculate sun position
            if self.center:
                solar_position = solarposition.get_solarposition(self.time, self.center.y, self.center.x)
                self.sun_azimuth = solar_position["azimuth"].values[0]
                self.sun_elevation = solar_position["elevation"].values[0]
                self.default_shadow_tree = self.create_default_shadow_tree()
            else:
                self.sun_azimuth = 0
                self.sun_elevation = 0
                self.default_shadow_tree = Polygon()

        def build_spatial_indices(self):
            """Build spatial indices for buildings and trees for faster spatial queries"""
            # Create an R-tree index for buildings
            self.building_idx = index.Index()
            for i, building in enumerate(self.buildings):
                self.building_idx.insert(i, building.bounds)
            
            # Create an R-tree index for trees
            self.tree_idx = index.Index()
            for i, tree in enumerate(self.trees):
                self.tree_idx.insert(i, tree.bounds)

        def get_data(self, input_file):
            """Get all buildings and trees from the input file and approximate center of the PBF"""
            # First pass: count buildings and trees
            class CounterHandler(osmium.SimpleHandler):
                def __init__(self):
                    super().__init__()
                    self.building_count = 0
                    self.tree_count = 0

                def way(self, w):
                    if "building" in w.tags:
                        self.building_count += 1
                
                def node(self, n):
                    if "natural" in n.tags and n.tags["natural"] == "tree":
                        self.tree_count += 1

            counter = CounterHandler()
            counter.apply_file(input_file, locations=True)
            total_count = counter.building_count + counter.tree_count
            
            # Second pass: collect data
            class DataHandler(osmium.SimpleHandler):
                def __init__(self, total_count):
                    super().__init__()
                    self.buildings = []
                    self.trees = []
                    
                    # For approx center calculation
                    self.min_lon, self.min_lat = float('inf'), float('inf')
                    self.max_lon, self.max_lat = float('-inf'), float('-inf')
                    self.node_count = 0
                    self.sample_rate = 1000  # Sample every 1000th node for center calculation

                def way(self, w):
                    if "building" in w.tags:
                        coords = [(n.lon, n.lat) for n in w.nodes]
                        if len(coords) >= 3:  # Ensure valid polygon
                            self.buildings.append(transform(transformer_to_meters.transform, Polygon(coords)))

                def node(self, n):
                    # Track approximate center
                    if self.node_count % self.sample_rate == 0:
                        self.min_lon = min(self.min_lon, n.lon)
                        self.min_lat = min(self.min_lat, n.lat)
                        self.max_lon = max(self.max_lon, n.lon)
                        self.max_lat = max(self.max_lat, n.lat)
                    self.node_count += 1
                    
                    # Process trees
                    if "natural" in n.tags and n.tags["natural"] == "tree":
                        lon, lat = n.lon, n.lat
                        point = transform(transformer_to_meters.transform, Point(lon, lat))
                        self.trees.append(point)
                
                def get_center(self):
                    if self.min_lon == float('inf'):
                        return None
                    center_lon = (self.min_lon + self.max_lon) / 2
                    center_lat = (self.min_lat + self.max_lat) / 2
                    return Point(center_lon, center_lat)

            handler = DataHandler(total_count)
            handler.apply_file(input_file, locations=True)
            
            center = handler.get_center()
            
            return handler.buildings, handler.trees, center

        def create_default_shadow_tree(self):
            """Create a tree shadow template that can be reused for all trees"""
            half_width_tree = self.default_tree_width / 2
            
            # Create square base for the tree
            tree_base = Polygon([
                (self.x_default_tree - half_width_tree, self.y_default_tree - half_width_tree),
                (self.x_default_tree + half_width_tree, self.y_default_tree - half_width_tree),
                (self.x_default_tree + half_width_tree, self.y_default_tree + half_width_tree),
                (self.x_default_tree - half_width_tree, self.y_default_tree + half_width_tree)
            ])
            
            return self.project_shadow_tree(tree_base, self.default_tree_height)

        def way(self, w):
            if "highway" in w.tags:
                # Calculate shade percentage
                shade_value = round(self.calculate_shade(w))
                
                # Copy existing tags and add shade information
                tags = list(w.tags)
                tags.append(osmium.osm.Tag("shade:percentage", f"{shade_value}%"))
                
                if shade_value >= 75:
                    tags.append(osmium.osm.Tag("shade", "yes"))
                elif shade_value >= 15:
                    tags.append(osmium.osm.Tag("shade", "partial"))
                else:
                    tags.append(osmium.osm.Tag("shade", "no"))

                # Create and write the modified way
                new_way = osmium.osm.mutable.Way(w)
                new_way.tags = tags
                self.pbf_writer.add_way(new_way)
                self.modified = True
            else:
                # Pass through unchanged
                self.pbf_writer.add_way(w)

        def node(self, n):
            self.pbf_writer.add_node(n)

        def relation(self, r):
            self.pbf_writer.add_relation(r)

        def close(self):
            self.pbf_writer.close()

        @lru_cache(maxsize=1000)
        def get_closest_points_to_road_direct(self, building, road):
            """Direct implementation with caching for shadow projection"""
            base_coords = list(building.exterior.coords)
            distances = [(Point(coord).distance(road), coord) for coord in base_coords]
            distances.sort(key=lambda x: x[0])
            return [distances[0][1], distances[1][1]]

        def project_shadow(self, building, building_height, road):
            """Project shadow from a building based on sun position"""
            if self.sun_elevation <= 0:
                return Polygon()  # No shadow if sun is below horizon
                
            shadow_length = building_height / np.tan(np.radians(self.sun_elevation))
            azimuth_radians = np.radians(self.sun_azimuth)
            
            # Get the points of the building closest to the road
            closest_points = self.get_closest_points_to_road_direct(building, road)
            
            # Project these points based on sun position
            projected_points = [
                (x + shadow_length * np.cos(azimuth_radians), y + shadow_length * np.sin(azimuth_radians))
                for x, y in closest_points
            ]

            # Create shadow polygon
            return Polygon([
                closest_points[0],
                projected_points[0],
                projected_points[1],
                closest_points[1]
            ])
        
        def project_shadow_tree(self, tree_base, tree_height):
            """Project shadow from a tree based on sun position"""
            if self.sun_elevation <= 0:
                return Polygon()  # No shadow if sun is below horizon
                
            shadow_length = tree_height / np.tan(np.radians(self.sun_elevation))
            azimuth_radians = np.radians(self.sun_azimuth)
            
            base_coords = list(tree_base.exterior.coords)[:4]
            shadow_parts = []
            
            # Generate shadows for each side of the square
            for i in range(len(base_coords)):
                p1 = base_coords[i]
                p2 = base_coords[(i + 1) % len(base_coords)]
                
                # Project points based on sun position
                p1_proj = (p1[0] + shadow_length * np.cos(azimuth_radians), 
                          p1[1] + shadow_length * np.sin(azimuth_radians))
                p2_proj = (p2[0] + shadow_length * np.cos(azimuth_radians), 
                          p2[1] + shadow_length * np.sin(azimuth_radians))
                
                quad = Polygon([p1, p2, p2_proj, p1_proj])
                shadow_parts.append(quad)
                
            # Merge all shadow parts
            return unary_union(shadow_parts)

        def process_building_batch(self, building_batch, way_line_meters, road_area):
            """Process a batch of buildings to calculate their shadows"""
            shadows = []
            for idx in building_batch:
                building = self.buildings[idx]
                if way_line_meters.distance(building.centroid) < self.building_area_spread:
                    # Estimate building height (using default since we don't have tags here)
                    shadow_polygon = self.project_shadow(building, self.default_building_height, way_line_meters)
                    if not shadow_polygon.is_empty:
                        # Only add if shadow intersects with road area
                        if shadow_polygon.intersects(road_area):
                            shadows.append(shadow_polygon)
            return shadows

        def process_tree_batch(self, tree_batch, road_area):
            """Process a batch of trees to calculate their shadows"""
            shadows = []
            for idx in tree_batch:
                tree = self.trees[idx]
                if road_area.distance(tree) < self.tree_area_spread:
                    # Translate the default tree shadow to the tree's position
                    tree_shadow = translate(self.default_shadow_tree, 
                                          xoff=tree.x-self.x_default_tree, 
                                          yoff=tree.y-self.y_default_tree)
                    if not tree_shadow.is_empty:
                        # Only add if shadow intersects with road area
                        if tree_shadow.intersects(road_area):
                            shadows.append(tree_shadow)
            return shadows

        def calculate_shade(self, way):
            """Calculate shade percentage for a way"""
            # Convert road to polygon in meter-based projection
            coords = [(n.lon, n.lat) for n in way.nodes]
            way_line_latlon = LineString(coords)
            way_line_meters = transform(self.transformer_to_meters.transform, way_line_latlon)
            road_area = way_line_meters.buffer(self.road_width)
            
            # Use road center for sun position if not already calculated
            if not self.center:
                solar_position = solarposition.get_solarposition(
                    self.time, coords[0][1], coords[0][0])
                self.sun_azimuth = solar_position["azimuth"].values[0]
                self.sun_elevation = solar_position["elevation"].values[0]
            
            all_shadows = []
            
            # Quick check if we have sun above horizon
            if self.sun_elevation <= 0:
                return 0  # No shadows if sun is below horizon
            
            # Find nearby buildings using spatial index
            road_bounds = road_area.buffer(self.building_area_spread).bounds
            nearby_building_ids = list(self.building_idx.intersection(road_bounds))
            
            # Skip calculation if no nearby buildings
            if nearby_building_ids:
                # Process buildings in parallel batches
                batch_size = max(1, len(nearby_building_ids) // (self.max_workers * 2))
                building_batches = [nearby_building_ids[i:i+batch_size] 
                                  for i in range(0, len(nearby_building_ids), batch_size)]
                
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_batch = {
                        executor.submit(self.process_building_batch, batch, way_line_meters, road_area): batch 
                        for batch in building_batches
                    }
                    
                    for future in as_completed(future_to_batch):
                        all_shadows.extend(future.result())
            
            # Merge building shadows
            if all_shadows:
                merged_building_shadows = unary_union(all_shadows)
                all_shadows = [merged_building_shadows]  # Keep merged result for later union with tree shadows
            
            # Find nearby trees using spatial index
            road_tree_bounds = road_area.buffer(self.tree_area_spread).bounds
            nearby_tree_ids = list(self.tree_idx.intersection(road_tree_bounds))
            
            # Skip calculation if no nearby trees
            if nearby_tree_ids:
                # Process trees in parallel batches
                batch_size = max(1, len(nearby_tree_ids) // (self.max_workers * 2))
                tree_batches = [nearby_tree_ids[i:i+batch_size] 
                              for i in range(0, len(nearby_tree_ids), batch_size)]
                
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_batch = {
                        executor.submit(self.process_tree_batch, batch, road_area): batch 
                        for batch in tree_batches
                    }
                    
                    for future in as_completed(future_to_batch):
                        all_shadows.extend(future.result())
            
            # If we have any shadows, calculate the intersection with the road
            if all_shadows:
                merged_all_shadows = unary_union(all_shadows)
                intersection = road_area.intersection(merged_all_shadows)
                shadow_area = intersection.area
                
                # Calculate percentage of road in shade
                return (shadow_area / road_area.area) * 100 if road_area.area > 0 else 0
            else:
                return 0  # No shadows found

    # File paths
    input_file = "C:\\Users\\jihen\\FiseA3\\procom\\meth_calcul\\procom_calcul\\test2.pbf"
    output_pbf = "C:\\Users\\jihen\\FiseA3\\procom\\meth_calcul\\procom_calcul\\test2_updatedd.pbf"
    
    # Process with optimized way modifier
    modifier = WayModifier(input_file, output_pbf)
    modifier.apply_file(input_file, locations=True)
    modifier.close()

    if modifier.modified:
        print(f"Roads have been modified and added to file {output_pbf}.")
    else:
        print(f"No roads were found or modified.")

    # Profile output
    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.strip_dirs().sort_stats("cumtime").print_stats(20)

    # Print total execution time
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f} seconds")