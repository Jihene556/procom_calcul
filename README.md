English version below 

Ce dépôt contient deux scripts pour traiter des données sous forme de fichiers pbf extraites de OpenStreetMap (OSM)   :
1) Script 1 : parks_forests/pbfmod.py : Détection des routes traversant des parcs et forêts et mise à jour du pourcentage d'ombre 
2) Script 2 : tree_integration.py : Calcul du pourcentage d'ombre des routes 

1. Détection et mise à jour des routes dans les parcs et forêts
Ce script traite un fichier .osm.pbf pour :
Identifier les parcs et forêts en extrayant les polygones correspondant aux tags landuse=park ou landuse=forest et mettre à jour les routes traversant ces zones en ajoutant un tag shade:percentage=100.

Installation
Assurez-vous d'avoir Python installé avec les dépendances suivantes :
pip install osmium shapely

Utilisation
Modifier les chemins des fichiers input_file et output_file dans le script selon votre arborescence de fichiers.

Exécuter le script :
python pbfmod.py.py

Résultat : 
Un fichier .osm.pbf mis à jour avec les routes modifiées.

2. Calcul du pourcentage d'ombre des routes

Ce script prend un fichier pbf et calcule la proportion des routes situées sous des zones ombragées calculant ainsi le pourcentage d'ombre sur chaque route, en se basant 
sur les bâtiments et les arbres et des données géospatiales.

Installation
Les bibliothèques suivantes sont nécessaires :

pip install osmium shapely

Utilisation
Modifier le chemin du fichier d'entrée dans le script.

Exécuter le script :
python integration_tree.py

Résultat
Le script affiche et enregistre les pourcentages d'ombre détectés sur les routes concernées.

Ces deux scripts peuvent être utilisés séparément selon les besoins d'analyse des données OSM.





This repository contains two scripts for processing .pbf files extracted from OpenStreetMap (OSM):

Script 1: parks_forests/pbfmod.py - Detects roads passing through parks and forests and updates their shade percentage.
Script 2: tree_integration.py - Calculates the percentage of road shading.

1. Detecting and Updating Roads in Parks and Forests
This script processes a .osm.pbf file to:
Identify parks and forests by extracting polygons corresponding to landuse=park or landuse=forest.
Update roads passing through these zones by adding a shade:percentage=100 tag.

Installation
Ensure you have Python installed with the following dependencies:
pip install osmium shapely

Usage
Modify the file paths for input_file and output_file in the script according to your file structure.

Run the script:
python pbfmod.py

Output
A .osm.pbf file with updated roads.

2. Calculating Road Shade Percentage   
This script takes a .pbf file and calculates the proportion of roads located under shaded areas, estimating the shade percentage for each road based on buildings, trees, and geospatial data.

Installation
The following libraries are required:
pip install osmium shapely

Usage
Modify the input file path in the script.

Run the script:
python tree_integration.py

Output
The script displays and saves the detected shade percentages for affected roads.

These two scripts can be used independently based on OSM data analysis needs.

