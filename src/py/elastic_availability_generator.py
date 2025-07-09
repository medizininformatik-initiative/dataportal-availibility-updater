import json
import logging
import os
import uuid


class ElasticAvailabilityGenerator:
    namespace_uuid_str = '00000000-0000-0000-0000-000000000000'
    extension = '.json'
    max_filesize_mb = 10

    def __init__(self, availability_input_dir, availability_output_dir, es_ontology_dir):
        self.availability_input_dir = availability_input_dir
        self.availability_output_dir = availability_output_dir
        self.es_ontology_dir = es_ontology_dir
        self.es_onto_tree = {}

        with open(os.path.join(self.availability_input_dir, 'stratum-to-context.json')) as fp:
            self.stratum_to_context = json.load(fp)

    def __get_contextualized_termcode_hash(self, context_node: dict, termcode_node: dict):

        context_termcode_hash_input = f"{context_node.get('system')}{context_node.get('code')}{context_node.get('version', '')}{termcode_node.get('system')}{termcode_node.get('code')}"

        namespace_uuid = uuid.UUID(self.namespace_uuid_str)
        return str(uuid.uuid3(namespace_uuid, context_termcode_hash_input))

    def get_avail_sum_for_all_children(self, parent_id):

        count = self.es_onto_tree[parent_id]["availability"]

        for child in self.es_onto_tree[parent_id]["children"]:
            count = count + self.get_avail_sum_for_all_children(child["contextualized_termcode_hash"])

        return count

    def convert_measure_score_to_ranges(self, measure_score):
        buckets = [0, 10, 100, 1000, 10000, 100000, 1000000]
        return max(b for b in buckets if measure_score >= b)

    def get_hashed_tree(self):

        directory = os.path.join(self.es_ontology_dir, "elastic")

        for filename in os.listdir(directory):
            if 'onto_es__ontology' in filename:
                filepath = os.path.join(directory, filename)

                logging.debug("Processing Ontology file: " + filepath)

                with open(filepath, 'r') as file:
                    for line in file:
                        line = line.strip()

                        if line:
                            obj = json.loads(line)

                            if "index" in obj:
                                cur_hash = obj["index"]["_id"]
                            else:

                                self.es_onto_tree[cur_hash] = {
                                    "availability": 0,
                                    "children": obj["children"]
                                }

    def update_availability_on_hash_tree(self):

        hash_set = set()

        for filename in os.listdir(self.availability_input_dir):
            if 'availability_report' in filename:
                filepath = os.path.join(self.availability_input_dir, filename)

                with open(filepath, "r") as f:
                    report = json.load(f)

                    for group in report["group"]:

                        for stratifier in group["stratifier"]:
                            if "stratum" in stratifier:

                                strat_code = stratifier["code"][0]["coding"][0]["code"]

                                if strat_code not in self.stratum_to_context:
                                    logging.debug(f"Stratifier {strat_code} not in stratum_to_context -> skipping")
                                    continue

                                context = self.stratum_to_context[strat_code]

                                for stratum in stratifier["stratum"]:
                                    measure_score = stratum["measureScore"]["value"]

                                    if "system" not in stratum["value"]["coding"][0]:
                                        continue

                                    strat_system = stratum["value"]["coding"][0]["system"]
                                    strat_code = stratum["value"]["coding"][0]["code"]

                                    termcode = {
                                        "system": strat_system,
                                        "code": strat_code
                                    }

                                    if context:
                                        hash = self.__get_contextualized_termcode_hash(context, termcode)

                                        hash_set.add(hash)
                                        if hash in self.es_onto_tree:
                                            self.es_onto_tree[hash]["availability"] = self.es_onto_tree[hash][
                                                                                          "availability"] + measure_score
                                        else:
                                            logging.debug(f'Context-Termcode combination not in ontology {context}, {termcode}')

    def __write_es_to_file(self, es_availability_inserts, max_filesize_mb, filename_prefix, extension, write_dir):

        current_file_subindex = 1
        current_file_size = 0
        count = 0

        current_file_name = os.path.join(write_dir, f"{filename_prefix}_{current_file_subindex}{extension}")
        with open(current_file_name, 'w+', encoding='UTF-8') as current_file:

            for insert in es_availability_inserts:

                count = count + 1
                current_line = f"{json.dumps(insert, ensure_ascii=False)}\n"
                current_file.write(current_line)
                current_file_size += len(current_line)

                if current_file_size > max_filesize_mb * 1024 * 1024 and count % 2 == 0:
                    current_file_subindex += 1
                    current_file_name = os.path.join(write_dir, f"{filename_prefix}_{current_file_subindex}{extension}")
                    current_file_size = 0
                    current_file.close()
                    current_file = open(current_file_name, 'w', encoding='UTF-8')

    def generate_availability(self):

        es_availability_inserts = []
        self.get_hashed_tree()
        self.update_availability_on_hash_tree()

        for key, value in self.es_onto_tree.items():
            sum_all_children = self.get_avail_sum_for_all_children(key)
            insert_hash = {"update": {"_id": key}}
            insert_availability = {
                "doc": {"availability": self.convert_measure_score_to_ranges(sum_all_children)}}

            if sum_all_children > 0:
                logging.debug(
                    f'key {key} is available with {sum_all_children} - converted to {self.convert_measure_score_to_ranges(sum_all_children)}')

            es_availability_inserts.append(insert_hash)
            es_availability_inserts.append(insert_availability)

        self.__write_es_to_file(es_availability_inserts, self.max_filesize_mb,
                                "es_availability_update", self.extension, self.availability_output_dir)
