import osmium

class WayModifier(osmium.SimpleHandler):
    def __init__(self, target_id, shade_value, output_pbf):
        super().__init__()
        self.target_id = target_id
        self.shade_value = shade_value
        self.pbf_writer = osmium.SimpleWriter(output_pbf)
        self.modified = False

    def way(self, w):
        if w.id == self.target_id:
            
            tags = []
            # Ajouter les tags existants
            for tag in w.tags:
                tags.append(osmium.osm.Tag(tag.k, tag.v))
            # Ajouter ou modifier le tag "shade_percentage"
            tags.append(osmium.osm.Tag("shade:percentage", f"{self.shade_value}%"))

            
            new_way = osmium.osm.mutable.Way(w)
            new_way.tags = tags  # Assigner les nouveaux tags à l'objet Way

            # Écrire le Way modifié dans le fichier de sortie
            self.pbf_writer.add_way(new_way)
            self.modified = True
        else:
            # Copier tous les autres objets Way tels quels
            self.pbf_writer.add_way(w)

    def node(self, n):
        # Copier les nœuds d'origine tels quels
        self.pbf_writer.add_node(n)

    def relation(self, r):
        # Copier les relations d'origine telles quelles
        self.pbf_writer.add_relation(r)

    def close(self):
        # Fermer le fichier de sortie
        self.pbf_writer.close()


# Chemins des fichiers
input_file = "C:\\users\\jihen\\FiseA3\\procom\\graphhopper_IMTA\\pays_de_la_loire-latest.osm.pbf"
output_pbf = "C:\\Users\\jihen\\FiseA3\\procom\\graphhopper_IMTA\\pays_de_la_loire-updated.osm.pbf"

# ID de la route à modifier et valeur de shade
TARGET_WAY_ID = 112186997
shade_value = 70

modifier = WayModifier(TARGET_WAY_ID, shade_value, output_pbf)
modifier.apply_file(input_file)
modifier.close()


if modifier.modified:
    print(f"Le Way avec l'ID {TARGET_WAY_ID} a été modifié et ajouté au fichier {output_pbf}.")
else:
    print(f"Aucune route avec l'ID {TARGET_WAY_ID} n'a été trouvée.")
