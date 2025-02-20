import osmium
from shapely.geometry import Polygon, LineString
import shapely.wkt

# --------------------------------------------------------------------
# Collector: Collect parks/forests (as polygons with metadata)
# --------------------------------------------------------------------
class ParkForestCollector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        # Each entry is a tuple: (polygon, name)
        self.parks = []
        self.nodes_cache = {}
        
    def node(self, n):
        # Cache node coordinates
        self.nodes_cache[n.id] = (n.location.lon, n.location.lat)
        
    def way(self, w):
        # Check if the way has a tag indicating it's a park or forest.
        if 'landuse' in w.tags and w.tags['landuse'] in ['park', 'forest']:
            coords = []
            for node in w.nodes:
                if node.ref in self.nodes_cache:
                    coords.append(self.nodes_cache[node.ref])
            if len(coords) >= 3:  # At least 3 points for a polygon
                try:
                    poly = Polygon(coords)
                    if poly.is_valid:
                        name = w.tags.get('name', 'unnamed')
                        self.parks.append((poly, name))
                        print(f"Found park/forest: {name} (way {w.id})")
                except Exception as e:
                    print(f"Error creating polygon for way {w.id}: {e}")

# --------------------------------------------------------------------
# Modifier: For each road way, if it lies inside (or intersects) any park/forest,
# update its tags and print which parks were hit.
# --------------------------------------------------------------------
class WayModifier(osmium.SimpleHandler):
    def __init__(self, parks, output_pbf):
        super().__init__()
        # parks is a list of tuples: (polygon, name)
        self.parks = parks
        self.pbf_writer = osmium.SimpleWriter(output_pbf)
        self.nodes_cache = {}
        self.modified_ways = 0
        
    def node(self, n):
        self.nodes_cache[n.id] = (n.location.lon, n.location.lat)
        self.pbf_writer.add_node(n)
        
    def way(self, w):
        coords = []
        for node in w.nodes:
            if node.ref in self.nodes_cache:
                coords.append(self.nodes_cache[node.ref])
        if len(coords) >= 2:  # Need at least 2 points for a line
            try:
                way_line = LineString(coords)
                
                # Use intersects() to catch even partially overlapping roads
                parks_hit = [name for (poly, name) in self.parks if poly.intersects(way_line)]
                
                if parks_hit:
                    self.modified_ways += 1
                    # Create new tags by copying existing ones and updating shade:percentage
                    tags = [osmium.osm.Tag(tag.k, tag.v) for tag in w.tags]
                    # Overwrite or add the shade:percentage tag (here we use "100")
                    tags.append(osmium.osm.Tag("shade:percentage", "100"))
                    
                    # Create a mutable copy of the way to update tags
                    try:
                        new_way = osmium.osm.mutable.Way(w)
                        new_way.tags = tags
                        self.pbf_writer.add_way(new_way)
                    except Exception as e:
                        print(f"Error modifying way {w.id}: {e}")
                        self.pbf_writer.add_way(w)
                    
                    print(f"Modified way {w.id} inside park(s): {', '.join(parks_hit)}")
                else:
                    self.pbf_writer.add_way(w)
            except Exception as e:
                print(f"Error processing way {w.id}: {e}")
                self.pbf_writer.add_way(w)
        else:
            self.pbf_writer.add_way(w)
                
    def relation(self, r):
        self.pbf_writer.add_relation(r)
        
    def close(self):
        self.pbf_writer.close()
        print(f"\nTotal ways modified: {self.modified_ways}")
        
# --------------------------------------------------------------------
# Main processing function
# --------------------------------------------------------------------
def process_osm_file(input_file, output_file):
    print("\nStarting OSM file processing...")
    
    print("\nPhase 1: Collecting parks and forests...")
    collector = ParkForestCollector()
    collector.apply_file(input_file)
    print(f"Found {len(collector.parks)} parks/forests")
    
    print("\nPhase 2: Processing ways...")
    modifier = WayModifier(collector.parks, output_file)
    modifier.apply_file(input_file)
    modifier.close()
    print("\nProcessing complete!")

if __name__ == "__main__":
    input_file = r"C:\Users\yahia\Documents\IMT\ProCom\nantes.osm.pbf"
    output_file = r"C:\Users\yahia\Documents\IMT\ProCom\nantes-updated.osm.pbf"
    
    process_osm_file(input_file, output_file)
