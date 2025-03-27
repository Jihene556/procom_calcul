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


''' 
This script tests Osmium by processing a PBF file:  
- It takes a calculated shade percentage.  
- It copies the content of the original PBF file into a new one.  
- It inserts the corresponding shade percentage for the specified 
way ID in the new file.  
This code will be generalized in the file *integration_tree* where we will 
enter a calculated shade percentage for each way of the pbf file
'''

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
            # Add existing tags
            for tag in w.tags:
                tags.append(osmium.osm.Tag(tag.k, tag.v))
            # Add or modify the tag "shade_percentage"
            tags.append(osmium.osm.Tag("shade:percentage", f"{self.shade_value}%"))

            
            new_way = osmium.osm.mutable.Way(w)
            new_way.tags = tags  # Assign new tags to the object way 

            # Write the modified way in the output file
            self.pbf_writer.add_way(new_way)
            self.modified = True
        else:
            # Copy all the other ways as they are
            self.pbf_writer.add_way(w)

    def node(self, n):
        # Copy the original nodes as they are
        self.pbf_writer.add_node(n)

    def relation(self, r):
        # Copy the original relations as they are 
        self.pbf_writer.add_relation(r)

    def close(self):
        # Close the output file 
        self.pbf_writer.close()


# File paths : to change according to where your your input file is located
input_file = "C:\\users\\jihen\\FiseA3\\procom\\graphhopper_IMTA\\pays_de_la_loire-latest.osm.pbf"
output_pbf = "C:\\Users\\jihen\\FiseA3\\procom\\graphhopper_IMTA\\pays_de_la_loire-updated.osm.pbf"

# ID of the way and the value of shade percenatage 
TARGET_WAY_ID = 112186997
shade_value = 70

modifier = WayModifier(TARGET_WAY_ID, shade_value, output_pbf)
modifier.apply_file(input_file)
modifier.close()


if modifier.modified:
    print(f"The way with the ID {TARGET_WAY_ID} was modified and added to the file {output_pbf}.")
else:
    print(f"No way with the ID {TARGET_WAY_ID} was found.")
