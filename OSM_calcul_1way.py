import overpy  # pour requêter l'API Overpass
from shapely.geometry import LineString, Polygon, Point  # pour les opérations géométriques
from pvlib import solarposition  # pour la position du soleil
import datetime
import numpy as np
import matplotlib.pyplot as plt

from shapely.ops import transform
from pyproj import CRS, Transformer

# Définir les systèmes de coordonnées
crs_latlon = CRS("EPSG:4326")  # Latitude/Longitude
crs_projected = CRS("EPSG:32630")  # UTM zone 30N (adaptée pour la zone de France de l'ouest)
transformer_to_meters = Transformer.from_crs(crs_latlon, crs_projected, always_xy=True) 
# always_xy = True means coordinates must be lon/lat (and not lat/lon)


considered_way_id = 112186997
#considered_way_id = 111194018
node_area_spread = 20
building_area_spread = 30
road_width = 10

default_height = 4
level_height = 2.8


# Récupérer la route depuis Overpass API
api = overpy.Overpass()

considered_way = api.query(f"""
    [out:json];
    (
    way(id:{considered_way_id});
    >;
    );
    out body geom;
""").ways[0]


# extract way coordinates
considered_way_coords = [(node.lon, node.lat) for node in considered_way.nodes]
# create line
considered_way_line_latlon = LineString(considered_way_coords)
# change scale (lon/lat -> meters)
considered_way_line_meters = transform(transformer_to_meters.transform, considered_way_line_latlon)
# add width
considered_road = considered_way_line_meters.buffer(road_width)


# Calcul de la position du soleil
longitude, latitude = considered_way_line_latlon.centroid.x, considered_way_line_latlon.centroid.y
solar_position = solarposition.get_solarposition(datetime.datetime.today(), latitude, longitude)
sun_azimuth = solar_position['azimuth'].values[0]
sun_elevation = solar_position['elevation'].values[0]
print(f"sun_elevation: {sun_elevation}")


# Get the buildings from Overpass API
result = api.query(f"""
    [out:json];
                   
    (
    way(id:{considered_way_id});             
    way["building"](around:{building_area_spread}); // Get the buildings around the nodes of the way
    >; // Get the nodes of the buildings
    );
                   
    out body geom;
""")


def way_to_polygon(way):
    """
    Convertit un objet overpy.Way en un Polygon Shapely en utilisant les coordonnées des nœuds,
    et le met à l'échelle (lon/lat -> mètres)
    
    :param way: Objet overpy.Way représentant un bâtiment
    :return: Polygon représentant le bâtiment
    """
    # Extraire les coordonnées de chaque nœud de la Way et les utiliser pour créer un polygone
    coords = [(node.lon, node.lat) for node in way.nodes]
    return transform(transformer_to_meters.transform, Polygon(coords))


def get_closest_points_to_road(building_base):
    """
    Trouve les deux points de la base du bâtiment les plus proches de la route.
    
    :param building_base: Polygon (Shapely) représentant la base du bâtiment
    :param road: LineString (Shapely) représentant la route
    
    :return: Liste de deux coordonnées (x, y) représentant les points les plus proches
    """
    global considered_way_line_meters
    
    # Extraire les sommets de la base
    base_coords = list(building_base.exterior.coords)
    
    # Calculer la distance de chaque sommet à la route
    distances = [(Point(coord).distance(considered_way_line_meters), coord) for coord in base_coords]
    
    # Trier par distance croissante
    distances.sort(key=lambda x: x[0])
    
    # Retourner les deux points les plus proches
    return [distances[0][1], distances[1][1]]


def project_shadow(building, building_height, sun_elevation, sun_azimuth):
    """
    Projette l'ombre d'un bâtiment (sous forme d'un overpy.Way) sur le sol en fonction de la hauteur,
    de l'inclinaison et de l'azimut du soleil.
    
    :param building: Objet Polygon Shapely représentant le bâtiment
    :param building_height: Hauteur du bâtiment (en mètres)
    :param sun_elevation: Élévation du soleil (en degrés)
    :param sun_azimuth: Azimut du soleil (en degrés, 0° est le nord, 90° est l'est)
    
    :return: Polygon représentant l'ombre projetée (shapely.geometry.Polygon)
    """    
    # Calculer la longueur de l'ombre en fonction de la hauteur du bâtiment et de l'élévation du soleil
    if sun_elevation > 0:
        shadow_length = building_height / np.tan(np.radians(sun_elevation))
        print(f"shadow_length: {shadow_length}")
    else:
        shadow_length = 0  # Soleil au niveau de l'horizon ou en dessous, ombre infinie ou absente

    # Calculer la direction de l'azimut en radians
    azimuth_radians = np.radians(sun_azimuth)
    
    # Get closest points to the road
    closest_points = get_closest_points_to_road(building)
    # Projeter les points de base dans la direction de l'ombre
    projected_points = [
        (
            x + shadow_length * np.cos(azimuth_radians), 
            y + shadow_length * np.sin(azimuth_radians)
        )
        for x, y in closest_points
    ]

    # Créer un polygone d'ombre avec les deux points de base et leurs projections
    shadow_polygon = Polygon([
        closest_points[0],
        projected_points[0],
        projected_points[1],
        closest_points[1]
    ])
 
    # Retourner le polygone représentant l'ombre projetée
    return shadow_polygon



fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

# # Représenter la route au sol
road_x, road_y = considered_road.exterior.xy
ax.plot(road_x, road_y, np.zeros_like(road_x), color='red', alpha=0.5)

# For each way:
# - if its a building:
#   - get the height OR the nb of levels if it exists and estimate the height
#     (if not, don't take the building into account, or consider 1 or 2 levels)
#   - apply projection function


# Projection des ombres et calcul de l'intersection
shadow_area = 0
for way in result.ways:
    if way.tags.get("building"): # if it's a building
        # estimate the height
        building_height = default_height
        if way.tags.get("height"):
            building_height = float(way.tags["height"])
        elif way.tags.get("building:levels"):
            building_height = level_height * float(way.tags["building:levels"])

        # Définir les coordonnées du bâtiment en 3D (supposons que le bâtiment soit un simple polygone vertical)
        building_polygon = way_to_polygon(way)
        x_building, y_building = building_polygon.exterior.xy
        # Afficher le bâtiment
        for i in range(len(x_building) - 1):
            ax.plot([x_building[i], x_building[i]], [y_building[i], y_building[i]], [0, building_height], color="blue")
            ax.plot([x_building[i], x_building[i+1]], [y_building[i], y_building[i+1]], [building_height, building_height], color="blue")
            ax.plot([x_building[i], x_building[i+1]], [y_building[i], y_building[i+1]], [0, 0], color="blue")


        shadow_length = building_height / np.tan(np.radians(sun_elevation))
        shadow_polygon = project_shadow(building_polygon, building_height, sun_elevation, sun_azimuth)
        # Afficher l'ombre
        shadow_x, shadow_y = shadow_polygon.exterior.xy
        ax.plot(shadow_x, shadow_y, np.zeros_like(shadow_x), color='gray', alpha=0.5)

        intersection = considered_road.intersection(shadow_polygon)
        shadow_area += intersection.area

# Calcul du pourcentage d'ombre
percentage_shadow = (shadow_area / considered_road.area) * 100
print(f"Pourcentage d'ombre: {percentage_shadow:.2f}%")



### Plot

# Configurer l'affichage 3D
# Pour afficher en orthonormal
min_x = min(road_x)
max_x = max(road_x)

min_y = min(road_y)
max_y = max(road_y)

max_diff = max(max_x-min_x, max_y-min_y)

ax.set_xlim(min_x, min_x + max_diff)
ax.set_ylim(min_y, min_y + max_diff)
ax.set_zlim(0, max_diff)

ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_zlabel("Hauteur (mètres)")
ax.set_title("Visualisation 3D du bâtiment, de l'ombre projetée et de la route")
plt.legend()
plt.show()
