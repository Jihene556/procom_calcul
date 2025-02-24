import osmium
import overpy
import datetime
from pvlib import solarposition
from shapely.geometry import LineString, Polygon, Point
from pyproj import CRS, Transformer
from shapely.ops import transform, unary_union
from shapely.affinity import translate
import numpy as np
from tqdm import tqdm

# Définir les systèmes de coordonnées
crs_latlon = CRS("EPSG:4326")  # WGS84 (latitude/longitude)
crs_projected = CRS("EPSG:32630")  # UTM pour projection en mètres
transformer_to_meters = Transformer.from_crs(crs_latlon, crs_projected, always_xy=True)


class WayModifier(osmium.SimpleHandler):
    def __init__(self, input_file, output_pbf):
        super().__init__()
        self.api = overpy.Overpass()
        self.transformer_to_meters = transformer_to_meters
        self.road_width = 10  # Largeur moyenne des routes
        self.input_file = input_file
        # Building parameters
        self.building_area_spread = 50  # Rayon pour récupérer les bâtiments autour des routes
        self.default_building_height = 4  # Hauteur par défaut des bâtiments (mètres)
        self.level_height = 2.8  # Hauteur moyenne par étage (mètres)
        # Tree parameters
        self.tree_area_spread = 20  # Rayon pour récupérer les arbres autour des routes
        self.default_tree_height = 5  # Hauteur par défaut des arbres (mètres)
        self.default_tree_width = 3  # Largeur par défaut des arbres (mètres)
        self.x_default_tree = 0
        self.y_default_tree = 0
        self.default_shadow_tree = self.create_default_shadow_tree()
        #
        self.pbf_writer = osmium.SimpleWriter(output_pbf)
        self.modified = False
        self.buildings = self.get_all_buildings(input_file)  # Récupération des bâtiments une seule fois
        self.trees = self.get_all_trees(input_file)  # Récupération des arbres

    def get_all_buildings(self, input_file):
        """Charge tous les bâtiments du fichier en amont pour éviter les requêtes Overpass répétées."""
        class BuildingHandler(osmium.SimpleHandler):
            def __init__(self):
                super().__init__()
                self.buildings = []

            def way(self, w):
                if "building" in w.tags:
                    coords = [(n.lon, n.lat) for n in w.nodes]
                    self.buildings.append(transform(transformer_to_meters.transform, Polygon(coords)))

        handler = BuildingHandler()
        handler.apply_file(input_file, locations=True)
        return handler.buildings

    def get_all_trees(self, input_file):
        """Charge tous les arbres du fichier en amont pour éviter les requêtes Overpass répétées."""
        class TreeHandler(osmium.SimpleHandler):
            def __init__(self):
                super().__init__()
                self.trees = []

            def node(self, n):
                if "natural" in n.tags and n.tags["natural"] == "tree":
                    lon, lat = n.lon, n.lat
                    point = transform(transformer_to_meters.transform, Point(lon, lat))
                    self.trees.append(point)

        handler = TreeHandler()
        handler.apply_file(input_file, locations=True)
        return handler.trees

    def create_default_shadow_tree(self):
        """Create a tree approximately in the center of the map and project its shadow"""
        half_width_tree = self.default_tree_width/2
        center = self.get_pbf_approx_center()
        center_meters = transform(transformer_to_meters.transform, center)
        self.x_default_tree, self.y_default_tree = center_meters.x, center_meters.y
        tree_base = Polygon([
                (self.x_default_tree - half_width_tree, self.y_default_tree - half_width_tree),
                (self.x_default_tree + half_width_tree, self.y_default_tree - half_width_tree),
                (self.x_default_tree + half_width_tree, self.y_default_tree + half_width_tree),
                (self.x_default_tree - half_width_tree, self.y_default_tree + half_width_tree)
            ])
        solar_position = solarposition.get_solarposition(datetime.datetime.today(), center.y, center.x)
        sun_azimuth = solar_position["azimuth"].values[0]
        #print(f"sun azimuth : {sun_azimuth}" )
        sun_elevation = solar_position["elevation"].values[0]
        return self.project_shadow_tree(tree_base, self.default_tree_height, sun_elevation, sun_azimuth)

    def get_pbf_approx_center(self, sample_rate=1000):
        """Estime le centre du PBF en analysant seulement 1 nœud sur 'sample_rate'."""
        class SampleBoundingBoxFinder(osmium.SimpleHandler):
            def __init__(self, sample_rate):
                super().__init__()
                self.min_lon, self.min_lat = float('inf'), float('inf')
                self.max_lon, self.max_lat = float('-inf'), float('-inf')
                self.sample_rate = sample_rate
                self.count = 0

            def node(self, n):
                if self.count % self.sample_rate == 0:  # Prend seulement 1 nœud sur sample_rate
                    self.min_lon = min(self.min_lon, n.lon)
                    self.min_lat = min(self.min_lat, n.lat)
                    self.max_lon = max(self.max_lon, n.lon)
                    self.max_lat = max(self.max_lat, n.lat)
                self.count += 1

        bbox_finder = SampleBoundingBoxFinder(sample_rate)
        bbox_finder.apply_file(self.input_file, locations=True)

        if bbox_finder.min_lon == float('inf'):
            print("Impossible de déterminer le centre : aucun point trouvé.")
            return None

        center_lon = (bbox_finder.min_lon + bbox_finder.max_lon) / 2
        center_lat = (bbox_finder.min_lat + bbox_finder.max_lat) / 2
        center = Point(center_lon, center_lat)
        return center

    def way(self, w):
        if "highway" in w.tags:
            # in the graphhopper code, shade percentage should be an integer that's why we have to round the value 
            shade_value = round(self.calculate_shade(w))
            #print(shade_value)
            tags = list(w.tags)  # Copier les tags existants
            tags.append(osmium.osm.Tag("shade:percentage", f"{shade_value}%"))  # Ajouter le nouveau tag

            if shade_value >= 75 and shade_value <= 100:
                tags.append(osmium.osm.Tag("shade", "yes"))
            elif shade_value < 75 and shade_value >= 15 :
                tags.append(osmium.osm.Tag("shade", "partial"))
            elif shade_value>= 0 and shade_value < 15 :
                tags.append(osmium.osm.Tag("shade", "no"))

            new_way = osmium.osm.mutable.Way(w)
            new_way.tags = tags

            self.pbf_writer.add_way(new_way)
            self.modified = True
        else:
            self.pbf_writer.add_way(w)

    def node(self, n):
        self.pbf_writer.add_node(n)

    def relation(self, r):
        self.pbf_writer.add_relation(r)

    def close(self):
        self.pbf_writer.close()

    def get_closest_points_to_road(self, building_base, road):
        base_coords = list(building_base.exterior.coords)
        distances = [(Point(coord).distance(road), coord) for coord in base_coords]
        distances.sort(key=lambda x: x[0])
        return [distances[0][1], distances[1][1]]

    def project_shadow(self, building, building_height, sun_elevation, sun_azimuth, road):
        if sun_elevation > 0:
            shadow_length = building_height / np.tan(np.radians(sun_elevation))
        else:
            return Polygon([])  # Pas d'ombre si le soleil est sous l'horizon

        azimuth_radians = np.radians(sun_azimuth)
        closest_points = self.get_closest_points_to_road(building, road)
        projected_points = [
            (x + shadow_length * np.cos(azimuth_radians), y + shadow_length * np.sin(azimuth_radians))
            for x, y in closest_points
        ]

        return Polygon([
            closest_points[0],
            projected_points[0],
            projected_points[1],
            closest_points[1]
        ])
    
    def project_shadow_tree(self, tree_base, tree_height, sun_elevation, sun_azimuth):
        if sun_elevation > 0:
            shadow_length = tree_height / np.tan(np.radians(sun_elevation))
        else:
            return Polygon([])  # Pas d'ombre si le soleil est sous l'horizon

        azimuth_radians = np.radians(sun_azimuth)
        
        base_coords = list(tree_base.exterior.coords)[:4]  # Prendre les 4 premiers points de l'arbre
        shadow_parts = []
        for i in range(len(base_coords)): # Générer les ombres pour chaque côté du carré
            p1 = base_coords[i]
            p2 = base_coords[(i + 1) % len(base_coords)] 
            # Projeter ces deux points
            p1_proj = (p1[0] + shadow_length * np.cos(azimuth_radians), p1[1] + shadow_length * np.sin(azimuth_radians))
            p2_proj = (p2[0] + shadow_length * np.cos(azimuth_radians), p2[1] + shadow_length * np.sin(azimuth_radians))
            quad = Polygon([p1, p2, p2_proj, p1_proj])
            shadow_parts.append(quad)
        shadow_polygon = unary_union(shadow_parts)

        return shadow_polygon

    def calculate_shade(self, way):
        # Convertir la route en polygone (zone impactée par l'ombre)
        coords = [(n.lon, n.lat) for n in way.nodes]
        way_line_latlon = LineString(coords)
        way_line_meters = transform(self.transformer_to_meters.transform, way_line_latlon)
        road_area = way_line_meters.buffer(self.road_width)

        # Obtenir la position du soleil
        longitude, latitude = way_line_latlon.centroid.x, way_line_latlon.centroid.y
        solar_position = solarposition.get_solarposition(datetime.datetime.today(), latitude, longitude)
        sun_azimuth = solar_position["azimuth"].values[0]
        #print(f"sun azimuth : {sun_azimuth}" )
        sun_elevation = solar_position["elevation"].values[0]

        all_shadows = [] # Stocker tous les polygones d'ombre
        
        # Calculer l'ombre projetée par les bâtiments environnants
        # Calculer l'ombre projetée par les bâtiments environnants
        print("Calcul des ombres des bâtiments...")
        for building in tqdm(self.buildings, desc="Bâtiments", unit="bâtiment"):
            if road_area.distance(building) < self.building_area_spread:
                # Estimer la hauteur du bâtiment
                building_height = self.default_building_height
                if "height" in way.tags:
                    building_height = float(way.tags["height"])
                elif "building:levels" in way.tags:
                    building_height = self.level_height * float(way.tags["building:levels"])
                shadow_polygon = self.project_shadow(building, building_height, sun_elevation, sun_azimuth, way_line_meters)
                all_shadows.append(shadow_polygon)

        merged_shadows_1 = unary_union(all_shadows)
        intersection = road_area.intersection(merged_shadows_1)
        #print(f"🛑 Ombre après bâtiments: {intersection.area}")

        # Calculer l'ombre projetée par les arbres environnants
        print("Calcul des ombres des arbres...")
        for tree in tqdm(self.trees, desc="Arbres", unit="arbre"):
            if road_area.distance(tree) < self.tree_area_spread:
                tree_shadow = translate(self.default_shadow_tree, xoff=tree.x-self.x_default_tree, yoff=tree.y-self.y_default_tree)
                all_shadows.append(tree_shadow)

        merged_shadows = unary_union(all_shadows)
        intersection = road_area.intersection(merged_shadows)
        #print(f"🌳 Ombre après bâtiments et arbres: {intersection.area}")
        shadow_area = intersection.area

        return (shadow_area / road_area.area) * 100 if road_area.area > 0 else 0


# Chemins des fichiers
input_file = "C:\\users\\jihen\\FiseA3\\procom\\meth_calcul\\procom_calcul\\test2.pbf"
output_pbf = "C:\\Users\\jihen\\FiseA3\\procom\\meth_calcul\\procom_calcul\\test2_updtd.pbf"

modifier = WayModifier(input_file, output_pbf)
modifier.apply_file(input_file, locations=True)
modifier.close()

if modifier.modified:
    print(f"Les routes ont été modifiées et ajoutées au fichier {output_pbf}.")
else:
    print(f"Aucune route n'a été trouvée ou modifiée.")