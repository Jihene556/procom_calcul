import osmium
import overpy
import datetime
from pvlib import solarposition
from shapely.geometry import LineString, Polygon, Point
from pyproj import CRS, Transformer
from shapely.ops import transform
import numpy as np

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
        self.building_area_spread = 50  # Rayon pour récupérer les bâtiments autour des routes
        self.default_height = 10  # Hauteur par défaut des bâtiments (mètres)
        self.level_height = 3  # Hauteur moyenne par étage (mètres)
        self.pbf_writer = osmium.SimpleWriter(output_pbf)
        self.modified = False
        self.buildings = self.get_all_buildings(input_file)  # Récupération des bâtiments une seule fois

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
        sun_elevation = solar_position["elevation"].values[0]

        # Calculer l'ombre projetée par les bâtiments environnants
        shadow_area = 0
        for building in self.buildings:
            if road_area.distance(building) < self.building_area_spread:
                building_height = self.default_height
                shadow_polygon = self.project_shadow(building, building_height, sun_elevation, sun_azimuth, way_line_meters)
                intersection = road_area.intersection(shadow_polygon)
                shadow_area += intersection.area

        return (shadow_area / road_area.area) * 100 if road_area.area > 0 else 0


# Chemins des fichiers
input_file = "C:\\users\\jihen\\FiseA3\\procom\\calcul\\pays_de_la_loire-latest.osm.pbf"
output_pbf = "C:\\Users\\jihen\\FiseA3\\procom\\calcul\\pays_de_la_loire-latest-updated.osm.pbf"

modifier = WayModifier(input_file, output_pbf)
modifier.apply_file(input_file, locations=True)
modifier.close()

if modifier.modified:
    print(f"Les routes ont été modifiées et ajoutées au fichier {output_pbf}.")
else:
    print(f"Aucune route n'a été trouvée ou modifiée.")