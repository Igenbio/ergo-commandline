#!/usr/bin/env python3
import sys
import argparse
import os
import hashlib
import requests
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor
from tqdm import tqdm
import json
import gzip
import sanitize_filename
from typing import List, Dict

ERGO_URL = 'https://ergo.igenbio.com'
ERGO_HOST = 'https://ergo.igenbio.com/REST/api/ERGO/v1.0/'
BLOCK_SIZE = 10240
VERSION = "1.0.0"
verify = True
import warnings
warnings.filterwarnings("ignore")

orientation = {
    "f": "forward",
    "r": "reverse",
    "ff": "forward, forward",
    "fr": "forward, reverse",
    "rf": "reverse, forward"
}

empty_project = {
    "data_elements": [],
    "name": "Data Upload ",
    "permissions": [

    ],
    "version": 1
}

def sizeof_fmt(num):
    for x in ['bytes','KB','MB','GB','TB']:
        if num < 1024.0:
            return "%3.1f%s" % (num, x)
        num /= 1024.0

class ProgressBar(tqdm):
    # from https://github.com/pypa/twine/blob/master/twine/repository.py
    def update_to(self, n):
        """Update the bar in the way compatible with requests-toolbelt.
        This is identical to tqdm.update, except ``n`` will be the current
        value - not the delta as tqdm expects.
        """
        self.update(n - self.n)  # will also do self.n = n



class HelpfulParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super(HelpfulParser, self).__init__(*args, **kwargs)
        self.epilog = F"Version {VERSION} Part of the ERGO(TM) Suite. (C) 2024 Igenbio, Inc."

    def error(self, message):
        sys.stderr.write('error: %s\n' % message)
        self.print_help()
        sys.exit(2)


# from https://gist.github.com/sampsyo/471779
class AliasedSubParsersAction(argparse._SubParsersAction):

    class _AliasedPseudoAction(argparse.Action):
        def __init__(self, name, aliases, help):
            dest = name
            if aliases:
                dest += ' (%s)' % ','.join(aliases)
            sup = super(AliasedSubParsersAction._AliasedPseudoAction, self)
            sup.__init__(option_strings=[], dest=dest, help=help)

    def add_parser(self, name, **kwargs):
        if 'aliases' in kwargs:
            aliases = kwargs['aliases']
            del kwargs['aliases']
        else:
            aliases = []

        parser = super(AliasedSubParsersAction, self).add_parser(name, **kwargs)

        # Make the aliases work.
        for alias in aliases:
            self._name_parser_map[alias] = parser
        # Make the help text reflect them, first removing old help entry.
        if 'help' in kwargs:
            help = kwargs.pop('help')
            self._choices_actions.pop()
            pseudo_action = self._AliasedPseudoAction(name, aliases, help)
            self._choices_actions.append(pseudo_action)

        return parser

def check_status(request, report=True) -> bool:
    if request.status_code != 200:
        if report:
            sys.stderr.write(F"Error: {request.status_code} {request.text}.")
        return False
    return True

class ERGO(object):

    def __init__(self, apikey):
        self.apikey = apikey
        self.headers = {"Authorization": "Bearer " + self.apikey}
        parser = HelpfulParser(prog="ergo", description="ERGO API command line interface.")
        subparser = parser.add_subparsers(dest="command")
        subparser.required = True

        genome = subparser.add_parser("genomes", help="List/Export Genomes in ERGO")
        genome_subparser = genome.add_subparsers(dest="task")
        genome_subparser.required = True
        genome_list_parser = genome_subparser.add_parser("list")
        genome_list_parser.set_defaults(func=self.list_genomes)

        genome_export_parser = genome_subparser.add_parser("export")
        genome_export_parser.add_argument("-g", "--genome", help="Genome to export", required=True, dest="genome")
        genome_export_parser.add_argument("-t", "--type", help="Data type to export", choices=["contigs", "proteins"],
                                          required=True, dest="type")
        genome_export_parser.add_argument("-o", "--output", help="Path to output to.", required=True, dest="output")
        genome_export_parser.set_defaults(func=self.export_genome)


        projects = subparser.add_parser("projects", help="Manage Projects in ERGO")
        projects_subparser = projects.add_subparsers(dest="task")
        projects_subparser.required = True
        projects_list_parser = projects_subparser.add_parser("list")
        projects_list_parser.set_defaults(func=self.list_projects)
        
        project = subparser.add_parser("project", help="Get info/download from a project in ERGO.")
        project_subparser = project.add_subparsers(dest="task")
        project_subparser.required = True

        project_download_parser = project_subparser.add_parser(
            "info", help="Get information about a Project.")
        project_download_parser.add_argument(
            "-i", "--id", help="Id of project to get info about.", required=True, dest="id")
        project_download_parser.add_argument("-f", "--files", help="Show only files on project.", required=False, action="store_true",
                                             default=False, dest="show_files")
        project_download_parser.add_argument("-l", "--long", help="Long view for files on project", required=False, action="store_true",
                                             default=False, dest="show_long")
        project_download_parser.add_argument("-t", "--type", help="Show files only of this type.", required=False,
                                             default=None, dest="type")
        project_download_parser.set_defaults(func=self.project_info)

        project_download_parser = project_subparser.add_parser("download", help="Downloads files from a project.")
        project_download_parser.add_argument(
            "-i", "--id", help="Id of project to download from.", required=True, dest="id")
        project_download_parser.add_argument("-f", "--filter", help="Filter elements by extension (e.g. fastq.gz)",
                                             required=False, nargs="+", dest="filter", default=[])
        project_download_parser.add_argument("-r", "--rename", help="Set the name of files by this choice.",
                                             required=False, dest="rename", default="ergo_name", 
                                             choices=["ergo_id", "ergo_name", "sample_name"])
        project_download_parser.set_defaults(func=self.project_download)

        project_create_parser = project_subparser.add_parser(
            "create", help="Create a new project.")
        project_create_parser.add_argument(
            "-n", "--name", help="Project Name", required=True, dest="name")
        project_create_parser.add_argument("-d", "--description", help="Project Descriptions",
                                           required=False, dest="description", default="")
        project_create_parser.add_argument("-p", "--permissions", help="List of user email addresses and "
                                           "their permission. e.g. example@igenbio.com:manage. Possible "
                                           "permissions are read, write, manage.",
                                           default=[],
                                           required=False, dest="permissions", nargs="+")
        project_create_parser.set_defaults(
            func=self.create_project_from_cmdline)

        data_elements = subparser.add_parser("files", help="Manage Data Elements in ERGO.")
        data_elements_subparser = data_elements.add_subparsers(dest="task")
        data_elements_subparser.required = True
        data_elements_list_parser = data_elements_subparser.add_parser("list")
        data_elements_list_parser.set_defaults(func=self.list_data_elements)

        data_elements_add_parser = data_elements_subparser.add_parser("add", help="Adds files to ERGO. Use 'reads' for read files.")
        data_elements_add_parser.add_argument("-f", "--files", help="Files to add to ERGO.", required=True,
                                              dest="files", type=argparse.FileType('rb'), nargs="+")
        data_elements_add_parser.add_argument("-g", "--genome", help="Short name of Genome to associate with element.",
                                              dest="genome", default=None)
        data_elements_add_parser.add_argument("-p", "--project", help="Id of project to add this element to.",
                                              dest="project", default=None)
        data_elements_add_parser.add_argument("-s", "--silent", default=False, help="No Output, except on error.",
                                              dest="silent", action="store_true")
        data_elements_add_parser.set_defaults(func=self.add_data_element)

        data_elements_delete_parser = data_elements_subparser.add_parser("delete")
        data_elements_delete_parser.add_argument("id", help="Id of element to delete.")
        data_elements_delete_parser.add_argument("-s", "--silent", default=False, help="No Output, except on error.",
                                              dest="silent", action="store_true")
        data_elements_delete_parser.set_defaults(func=self.delete_data_element)

        data_elements_dl_parser = data_elements_subparser.add_parser("download")
        data_elements_dl_parser.add_argument("-i", "--id", help="Id of element to download.", required=True, dest="id")
        data_elements_dl_parser.set_defaults(func=self.download_data_element)

        reads = subparser.add_parser("reads", help="Uploads read files to ERGO")
        reads.add_argument("-1", "--first", help="List of Reads to Add to ERGO.", required=True, dest="first",
                           type=argparse.FileType("rb"), nargs="+")
        reads.add_argument("-2", "--second", help="List of Read pairs to Add to ERGO.", required=False, dest="second",
                           type=argparse.FileType("rb"), nargs="+")
        reads.add_argument("-o", "--orientation", help="Orientation of read pairs.", required=False, dest="orientation",
                           type=str, choices=["fr", "rf", "ff"], default="fr")
        reads.add_argument("--interleaved", help="Reads are interleaved", required=False, dest="interleaved",
                           default=False, action="store_true")
        reads.add_argument("-p", "--project",
                           help="Id of project to add this element to, or \"new\" to create a new project.",
                           dest="project", default="new")
        reads.add_argument("-g", "--genome", help="Short name of Genome to associate with element.",
                           dest="genome", default=None)
        reads.add_argument("-s", "--silent", default=False, help="No Output, except on error.",
                           dest="silent", action="store_true")
        reads.add_argument("-a", "--auto-meta", help="Attempt to auto detect sample name from file name.", action="store_true", default=False)
        reads.set_defaults(func=self.handle_reads)

        workflows = subparser.add_parser("workflows", help="Manage Workflows in ERGO")
        workflows_subparser = workflows.add_subparsers(dest="task")
        workflows_list = workflows_subparser.add_parser("list")
        workflows_list.set_defaults(func=self.list_workflows)

        workflows_details = workflows_subparser.add_parser("details")
        workflows_details.add_argument("-i", "--id", help="Id of workflow to get details of.", dest="id", default=None, required=True)
        workflows_details.add_argument("--json", help="Output json", dest="output_json", default=False, required=False, action="store_true")
        workflows_details.set_defaults(func=self.get_workflow_details)

        workflows_delete = workflows_subparser.add_parser("delete")
        workflows_delete.add_argument("-i", "--id", help="Id of workflow to get details of.", dest="id", default=None, required=True)
        workflows_delete.set_defaults(func=self.delete_workflow)

        workflows_download = workflows_subparser.add_parser("download")
        workflows_download.add_argument(
            "-i", "--id", help="Id of workflow to download from.", dest="id", default=None, required=True)
        workflows_download.add_argument("--inputs", help="Download input files.",
                                        dest="download_inputs", default=False, required=False, action="store_true")
        workflows_download.add_argument("--outputs", help="Download output files.",
                                        dest="download_outputs", default=False, required=False, action="store_true")
        workflows_download.add_argument("-r", "--rename", help="Set the name of files by this choice.",
                                        required=False, dest="rename", default="ergo_name",
                                        choices=["ergo_id", "ergo_name", "sample_name"])
        workflows_download.set_defaults(func=self.download_workflow)

        workflows_create = workflows_subparser.add_parser("create")
        workflows_create_subparser = workflows_create.add_subparsers(dest="task")

        workflows_create_list = workflows_create_subparser.add_parser("list")
        workflows_create_list.set_defaults(func=self.list_creatable_workflows)

        workflows_create_params = workflows_create_subparser.add_parser("params")
        workflows_create_params.add_argument("-t", "--task-name", help="Task name to get workflow params for.", dest="task_name", required=True)
        workflows_create_params.set_defaults(func=self.get_workflow_params)
        
        workflows_create_new = workflows_create_subparser.add_parser("new")
        workflows_create_new.add_argument("--params", help="Parameters file.", dest="params", required=True)
        workflows_create_new.add_argument("-p", "--project-id", help="Id of the project to add this workflow to.", dest="project_id", required=True)
        workflows_create_new.set_defaults(func=self.create_workflow)

        workflows_update = workflows_subparser.add_parser("update")
        workflows_update.add_argument("-i", "--id", help="Id of the workflow to update.", dest="id", required=True)
        workflows_update.add_argument("-f", "--inputs", help="Id of files to add to inputs of workflow.", dest="inputs", required=False, nargs="+")
        workflows_update.set_defaults(func=self.update_workflow)

        workflows_start = workflows_subparser.add_parser("start")
        workflows_start.add_argument(
            "-i", "--id", help="Id of workflow to start.", dest="id", default=None, required=True)
        workflows_start.set_defaults(func=self.start_workflow)

        workflows_start = workflows_subparser.add_parser("stop")
        workflows_start.add_argument(
            "-i", "--id", help="Id of workflow to stop.", dest="id", default=None, required=True)
        workflows_start.set_defaults(func=self.stop_workflow)

        parser.set_defaults(func=lambda _args: parser.print_help())
        args = parser.parse_args()
        args.func(args)

    def delete_data_element(self, args):
        r = requests.delete(ERGO_HOST + "user/data_elements/" + args.id, headers=self.headers, verify=verify)
        if check_status(r):
            if not args.silent:
                sys.stdout.write(r.text)

    def update_data_element(self, element, silent=False):
        r = requests.put(ERGO_HOST + "user/data_elements/" + element["id"], json=element,
                         headers=self.headers, verify=verify)
        if check_status(r):
            if not silent:
                sys.stdout.write("Data Element Updated.\n")


    def update_project(self, project, silent=False):
        r = requests.put(ERGO_HOST + "projects/" + project["id"], json={"project": project},
                         headers=self.headers, verify=verify)
        if check_status(r):
            if not silent:
                sys.stdout.write("Project Updated.\n")

    def get_project(self, id):
        r = requests.get(ERGO_HOST + "projects/" + id,
                         headers=self.headers, verify=verify)
        if check_status(r):
            return r.json()["project"]

    def create_project(self, project):
        r = requests.post(ERGO_HOST + "projects", json={"project": project}, headers=self.headers, verify=verify)
        if check_status(r):
            return r.json()["project"]

    def create_project_from_cmdline(self, args):
        project = dict(name=args.name, description=args.description)
        if len(args.permissions) > 0:
            users = self.get_users()
            users_dict = {}
            for u in users:
                users_dict[u['email_address'].lower()] = u['id']
            permissions = []
            for p in args.permissions:
                if ":" not in p:
                    sys.stderr.write("Expected permission to specified as <email_address>:<permission>.")
                    exit(1)
                parts = p.lower().split(":")
                if parts[0] not in users_dict:
                    sys.stderr.write("Unknown user.")
                    exit(1)
                if parts[1] not in ["manage", "write", "read"]:
                    sys.stderr.write("Invalid permission.")
                    exit(1)
                permissions.append(dict(user=dict(id=users_dict[parts[0]]), permission=parts[1]))
            u = self.get_user()
            permissions.append(dict(user=u, permission="manage"))
            project["permissions"] = permissions

        result = self.create_project(project)
        if result:
            sys.stdout.write(F"{result['id']}")

    def upload(self, f, silent=False, genome=None, project=None):
        total_bytes = os.path.getsize(f.name)
        pbar = ProgressBar(desc="Uploading %s" % f.name, total=total_bytes, unit="bytes", unit_scale=True,
                           disable=silent)
        fields = {"file": (f.name, f, 'text/plain')}
        if genome:
            fields["genome"] = genome
        data = MultipartEncoder(fields=fields)
        monitor = MultipartEncoderMonitor(data, callback=lambda m: pbar.update_to(m.bytes_read))
        headers = self.headers.copy()
        headers.update({'Content-Type': monitor.content_type})
        r = requests.post(ERGO_HOST + "user/data_elements", data=monitor, headers=headers, verify=verify)
        pbar.close()
        sys.stdout.write("Processing...\n")
        if check_status(r):
            results = r.json()
            data_element = results["data_element"]
            if project:
                project = self.get_project(project)
                project["data_elements"].append(data_element)
                self.update_project(project, project)
            return data_element

    def add_data_element(self, args):
        for f in args.files:
            de = self.upload(f, args.silent, args.genome, args.project)
            sys.stdout.write(ERGO_URL + "#!file/" + de["id"] + "\n")

    def get_users(self) -> List[Dict]:
        r = requests.get(F"{ERGO_HOST}/users", verify=verify, headers=self.headers)
        if check_status(r, report=True):
            return r.json()["users"]
        else:
            raise RuntimeError("Couldn't get users.")

    def auto_set_sample_names(self, args, files: list):
        r = requests.post(F"{ERGO_HOST}user/detect_read_metadata", json=dict(data_elements=files), verify=verify, headers=self.headers)
        if check_status(r, False):
            if not args.silent:
                sys.stdout.write("Set sample names and other metadata from file names.")
        else:
            sys.stderr.write("Couldn't set sample names/metadata from files names.")

    def handle_reads(self, args):
        if args.project == "new":
            project = empty_project
            user = self.get_user()
            project["permissions"].append({
                "permission": "manage",
                "user": user
            })
            project = self.create_project(project)
            args.project = project["id"]
        if not args.second:
            # not paired end
            for f in args.first:
                de = self.upload(f, silent=args.silent, genome=args.genome, project=args.project)
                sys.stdout.write(ERGO_URL + "#!file/" + de["id"] + "\n")
                de = self.get_data_element(de["id"])

                de["metadata"]["interleaved"] = args.interleaved
                if args.interleaved:
                    de["metadata"]["orientation"] = orientation[args.orientation]
                else:
                    de["metadata"]["orientation"] = orientation[args.orientation[0]]
                self.update_data_element(de)
                self.auto_set_sample_names(args, [de])
        elif len(args.first) == len(args.second):
            pairs = zip(args.first, args.second)
            for p1, p2 in pairs:
                p1_de = self.upload(p1, silent=args.silent, genome=args.genome, project=args.project)
                p2_de = self.upload(p2, silent=args.silent, genome=args.genome, project=args.project)
                p1_de = self.get_data_element(p1_de["id"])
                p2_de = self.get_data_element(p2_de["id"])
                p1_de["metadata"]["orientation"] = orientation[args.orientation[0]]
                p1_de["metadata"]["pair"] = {"id": p2_de["id"]}
                sys.stdout.write(ERGO_URL + "#!file/" + p1_de["id"] + "\n")
                p2_de["metadata"]["orientation"] = orientation[args.orientation[1]]
                p2_de["metadata"]["pair"] = {"id": p1_de["id"]}
                sys.stdout.write(ERGO_URL + "#!file/" + p2_de["id"] + "\n")
                self.update_data_element(p1_de)
                self.update_data_element(p2_de)
                self.auto_set_sample_names(args, [p1_de, p2_de])


            sys.stdout.write(ERGO_URL + "#!/projects/" + args.project + "\n")

        else:
            sys.stderr.write("Lists -1 and -2 must be of equal length for paired end reads.")


    def list_genomes(self, args):
        r = requests.get(ERGO_HOST + "genomes", headers=self.headers, verify=verify)
        if check_status(r):
            genomes = r.json()["genomes"]
            for g in genomes:
                sys.stdout.write("{0}\t{1}\t{2}\n".format(g["short_name"], g["long_name"], g["domain"]))


    def export_genome(self, args):
        if args.type == "contigs":
            self.export_genome_sequences(args)
        elif args.type == "proteins":
            self.export_genome_protein_sequences(args)


    def export_genome_protein_sequences(self, args):
        r = requests.get(ERGO_HOST + F"genomes/{args.genome}/features", headers=self.headers, verify=verify)
        if check_status(r):
            features = r.json()["features"]
            print(F"Exporting {len(features)} features.")
            with open(args.output, "w") as fh:
                for f in tqdm(features, total=len(features)):
                    if f["type"] == "orf":
                        r = requests.get(ERGO_HOST + F"genomes/{args.genome}/features/{f['name']}",
                                         headers=self.headers, verify=verify)
                        if r.status_code == 200:
                            f = r.json()["feature"]
                            fh.write(F'>{f["name"]} {len(f["translation"])} aa\n')
                            for i in range(0, len(f["translation"]), 50):
                                fh.write(F'{f["translation"][i:i + 50]}\n')
                        else:
                            sys.stderr.write(F"ERROR Downloading: {f['name']} {r.status_code}")


    def export_genome_sequences(self, args):
        r = requests.get(ERGO_HOST + F"genomes/{args.genome}/sequences", headers=self.headers, verify=verify)
        if check_status(r):
            sequences = r.json()["sequences"]
            with open(args.output, "w") as fh:
                for s in tqdm(sequences, total=len(sequences)):
                    r = requests.get(ERGO_HOST + F"genomes/{args.genome}/sequences/{s['name']}", headers=self.headers, verify=verify)
                    if check_status(r, False):
                        sequence = r.json()["sequence"]
                        fh.write(F'>{sequence["name"]} {s["size"]}nt\n')
                        for i in range(0, len(sequence["sequence"]), 50):
                            fh.write(F'{sequence["sequence"][i:i + 50]}\n')
                    else:
                        sys.stderr.write(F"ERROR Downloading: {s['name']} {r.status_code}")

    def list_projects(self, args):
        r = requests.get(ERGO_HOST + "projects", headers=self.headers, verify=verify)
        if check_status(r):
            projects = r.json()["projects"]
            for p in projects:
                sys.stdout.write("{0}\t{1}\t{2}\n".format(p["id"], p["name"], p["description"]))

    def get_data_element(self, did):
        r = requests.get(ERGO_HOST + "user/data_elements/{0}".format(did), headers=self.headers, verify=verify)
        if check_status(r):
            return r.json()["data_element"]
        raise RuntimeError

    def download_data_element(self, did_or_args, rename):
        did = did_or_args
        if hasattr(did_or_args, "id"):
            did = did_or_args.id
        de = self.get_data_element(did)
        local_name = F"{did}.{de['type']['extension']}"
        new_name = local_name
        if rename == "ergo_name":
            new_name = de["name"]
        elif rename == "sample_name":
            if 'sample_name' not in de['metadata']:
                sys.stderr.write(F"Cannot name {de['id']} - {de['name']} from sample name as"
                 F" there is no sample name present. Using 'ergo_name' {de['name']}\n")
                new_name = de["name"]
            else:
                new_name = de['metadata']['sample_name']
                if 'orientation' in de['metadata']:
                    if de['metadata']['orientation'] == "forward":
                        new_name = F"{new_name}_R1"
                    elif de['metadata']['orientation'] == "reverse":
                        new_name = F"{new_name}_R2"
                    else:
                        raise NotImplementedError(de['metadata']['orientation'])
                new_name = F"{new_name}.{de['type']['extension']}"

        local_name = sanitize_filename.sanitize(local_name)
        new_name = sanitize_filename.sanitize(new_name)

        if os.path.exists(local_name):
            print(f"{local_name} exists locally, verifying checksums")
            checksum = self.checksum_file(local_name, algorithm=de['metadata']['checksum']['algorithm'], force_chunked_output=True)
            if checksum == de['metadata']['checksum']['value']:
                print("Checksums match, skipping download")
                return
            else:
                print("Checksums do not match, re-downloading")
        r = requests.get(ERGO_HOST + "user/data_elements/{0}/download".format(did), headers=self.headers, verify=verify, stream=True)
        if r.status_code == 200:
            total_bytes = int(de["size"])
            progress = tqdm(total=total_bytes, unit='B', unit_scale=True, desc=new_name, leave=True)
            with open(local_name, "wb") as fh:
                for data in r.iter_content(BLOCK_SIZE):
                    fh.write(data)
                    progress.update(len(data))
            progress.close()
        if new_name != local_name:
            if os.path.exists(new_name):
                sys.stderr.write(F"\r\n\nCannot rename {local_name} to {new_name} because path already exists. Stopping execution ...\n")
                exit(1)
            os.rename(local_name, new_name)
            #print(F"\r\nRenamed {local_name} -> {new_name}.")
        

    def project_info(self, args):
        project = self.get_project(args.id)
        if args.show_files:
            elements = project['data_elements']
            if args.type:
                elements = [e for e in elements if e['type']['extension'].lower() == args.type.lower()]
            if args.show_long:
                print(F"Files for {args.id} - {project['name']}:")
                for e in elements:
                    sn = e['metadata'].get('sample_name', "")
                    print(F"{e['id']}\t{e['name']}\t{e['type']['extension']}\t{sn}")
            else:
                sys.stdout.write(" ".join([e["id"] for e in elements]))
        else:
            print(F"Id:\t{project['id']}")
            print(F"Name:\t{project['name']}")
            print(F"Description:\t{project['description']}")
            print(F"Date Created:\t{project['date_created']}")
            print(F"Size:\t{sizeof_fmt(project['size'])}")
            print(F"Permissions:")
            print(F"{'Email':>30}{'Permission':>20}")
            for p in project['permissions']:
                print(F"{p['user']['email_address']:>30}{p['permission']:>20}")
            element_types = {}
            for e in project['data_elements']:
                if not e['type']['extension'] in element_types:
                    element_types[e['type']['extension']] = 0
                element_types[e['type']['extension']] += 1
            print(F"Files:")
            print(F"{'Type':>30}{'Number':>20}")
            for (k, v) in element_types.items():
                print(F"{k:>30}{v:>20}")
            

    def project_download(self, args):
        project = self.get_project(args.id)
        for de in project["data_elements"]:
            if len(args.filter) > 0:
                if de["type"]["extension"] in args.filter:
                    self.download_data_element(de["id"], args.rename)
            else:
                self.download_data_element(de["id"], args.rename)

    def list_data_elements(self, args):
        r = requests.get(ERGO_HOST + "user/data_elements", headers=self.headers, verify=verify)
        if check_status(r):
            data_elements = r.json()["data_elements"]
            for de in data_elements:
                sys.stdout.write("{0}\t{1}\t{2}\n".format(de["id"], de["name"], de["type"]["extension"]))

    def list_workflows(self, args):
        r = requests.get(ERGO_HOST + "pipelines/runs", headers=self.headers, verify=verify)
        if check_status(r):
            workflows = r.json()["runs"]
            sys.stdout.write(F"id\tname\tstatus\tdate submitted\tdate started\tdate completed\n")
            for w in workflows:
                sys.stdout.write(F"{w['id']}\t{w['definition']['display_name']}\t{w['status']}\t{w['date_submitted']}\t{w['date_started']}\t{w['date_completed']}\n")

    def get_workflow(self, wid) -> dict:
        r = requests.get(f"{ERGO_HOST}pipelines/runs/{wid}", headers=self.headers, verify=verify)
        if check_status(r):
            return r.json()['run']

    def save_workflow(self, workflow) -> dict:
        r = requests.put(f"{ERGO_HOST}pipelines/runs/{workflow['id']}", json=dict(pipeline_run=workflow), headers=self.headers, verify=verify)
        if check_status(r):
            return r.json()['pipeline_run']
        else:
            raise RuntimeError

    def update_workflow(self, args):
        elements = {}
        for i in args.inputs:
            try:
                e = self.get_data_element(i)
                if e["type"]["extension"].lower() == "fastq.gz":
                    if e["metadata"]["orientation"] == "forward":
                        elements[i] = e
            except RuntimeError as e:
                sys.stderr.write(f"Couldn't find Data element with id: {i}.")
        w = self.get_workflow(args.id)
        if w:
            sys.stdout.write(F"Adding {len(elements.keys())} as input files (and their corresponding pairs, if present).")
            w['definition']['inputs'] = [dict(data_element_id=e) for e in elements.keys()]
            try:
                self.save_workflow(w)
            except RuntimeError as e:
                sys.stderr.write(f"Couldn't save workflow with id {args.id}.")
        else:
            sys.stderr.write(f"Couldn't find workflow with id {args.id}.")


    def get_workflow_details(self, args):
        w = self.get_workflow(args.id)
        if w:
            if args.output_json:
                sys.stdout.write(json.dumps(w, indent=4))
            else:
                sys.stdout.write(F"Id: {w['id']}\n")
                sys.stdout.write(F"User: {w['user']}\n")
                sys.stdout.write(F"Display Name: {w['definition']['display_name']}\n")
                sys.stdout.write(F"Description: {w['definition']['description']}\n")
                sys.stdout.write(F"Status: {w['status']}\n")
                sys.stdout.write(F"Completion: {w['completeness'][0]} of {w['completeness'][1]} steps complete.\n")
                sys.stdout.write(F"Steps:\n")
                sys.stdout.write("\tNumber\tName\tStatus\t\n")
                w['steps'].sort(key=lambda v: v['definition']['number'])
                for s in w['steps']:
                    error_message = ""
                    if 'error_message' in s['definition']:
                        error_message = s['definition']['error_message']
                    sys.stdout.write(F"\t{s['definition']['number']}\t{s['name']}\t{s['status']}\t{error_message}\n")
                sys.stdout.write(F"Inputs: {[i['data_element_id'] for i in w['definition']['inputs'] if 'data_element_id' in i]}\n")
                sys.stdout.write(F"Outputs: {[i['data_element_id'] for i in w['definition']['outputs'] if 'data_element_id' in i]}\n")

    def download_workflow(self, args):
        r = requests.get(f"{ERGO_HOST}pipelines/runs/{args.id}", headers=self.headers, verify=verify)
        if check_status(r):
            w = r.json()["run"]
            if args.download_inputs:
                for i in w['definition']['inputs']:
                    if 'data_element_id' in i:
                        self.download_data_element(i["data_element_id"], args.rename)
            if args.download_outputs:
                for i in w['definition']['outputs']:
                    if 'data_element_id' in i:
                        self.download_data_element(i["data_element_id"], args.rename)

    def delete_workflow(self, args):
        r = requests.delete(f"{ERGO_HOST}pipelines/runs/{args.id}", headers=self.headers, verify=verify)
        if check_status(r):
            sys.stdout.write(F"Deleted {args.id}.")

    def get_creatable_workflows(self, args) -> list:
        r = requests.get(f"{ERGO_HOST}pipelines", headers=self.headers, verify=verify)
        if check_status(r):
            pipelines = r.json()["pipelines"]
            return pipelines

    def list_creatable_workflows(self, args):
        ws = self.get_creatable_workflows(args)
        sys.stdout.write(F"task name\tname\tdescription\n")
        for w in ws:
            sys.stdout.write(F"{w['task_name']}\t{w['display_name']}\t{w['description']}\n")
            

    def get_workflow_params(self, args):
        ws = self.get_creatable_workflows(args)
        for w in ws:
            if w['task_name'] == args.task_name:
                print(json.dumps(w, indent=4))

    def create_workflow(self, args):
        data = {"project_id": args.project_id}
        with open(args.params) as fh:
            pipeline = json.load(fh)
            data["pipeline"] = pipeline
        
        r = requests.post(f"{ERGO_HOST}pipelines", json=data, headers=self.headers, verify=verify)
        if check_status(r):
            response = r.json()["pipeline_run"]
            sys.stdout.write(F"{response['id']}\n")

    def start_workflow(self, args):
        r = requests.post(f"{ERGO_HOST}pipelines/runs/{args.id}/run", headers=self.headers, verify=verify)
        if check_status(r):
            sys.stdout.write("Success")

    def stop_workflow(self, args):
        w = self.get_workflow(args.id)
        if not w:
            sys.stderr.write(F"Couldn't find workflow with id: {args.id}.")
        w['status'] = "ABORTED"
        self.save_workflow(w)

    def get_user(self) -> Dict:
        r = requests.get(ERGO_HOST + "user", headers=self.headers, verify=verify)
        if check_status(r):
            r.close()
            return r.json()["user"]
        else:
            r.close()
            raise RuntimeError

    def calculate_s3_etag(self, file_path, chunk_size=8 * 1024 * 1024, force_chunked_output=False):
        """
        Calculates the s3 etag of a localfile.
        """
        # from https://stackoverflow.com/a/43819225/438106
        md5s = []

        with open(file_path, 'rb') as fp:
            while True:
                data = fp.read(chunk_size)
                if not data:
                    break
                # not used for security
                md5s.append(hashlib.md5(data)) # nosec

        if len(md5s) == 1 and force_chunked_output is False:
            return '"{}"'.format(md5s[0].hexdigest())

        digests = b''.join(m.digest() for m in md5s)
        # not used for security
        digests_md5 = hashlib.md5(digests) # nosec
        # not used for security
        return '"{}-{}"'.format(digests_md5.hexdigest(), len(md5s)) # nosec

    def checksum_file(self, filename, algorithm="md5", force_chunked_output=False):
        """
        Computes and returns a checksum on the supplied file using the supplied algorithm
        :param filename: File to compute the checksum on
        :type filename: str
        :param algorithm: Default is md5. Raises NotImplementedError if the algorithm isn't available.
        :type algorithm: str
        :return: checksum
        :rtype: str
        """
        import os.path
        import subprocess
        from smart_open.s3 import DEFAULT_MIN_PART_SIZE
        if algorithm not in ["md5", "sha", "sha1", "md4", "md2", "mdc2", "sha224", "sha256", "sha384", "sha512",
                             "etag"]:
            raise NotImplementedError("Algorithm: %s not available." % algorithm)
        if not os.path.isfile(filename):
            raise ValueError("File not found: %s" % filename)
        if algorithm == "etag":
            return self.calculate_s3_etag(filename, chunk_size=DEFAULT_MIN_PART_SIZE,
                                     force_chunked_output=force_chunked_output)
        else:
            result = subprocess.check_output(
                ["openssl", algorithm, filename],
                stderr=subprocess.STDOUT).decode("latin1")
            return result.split("= ")[1].rstrip()


if __name__ == '__main__':
    apikey = None
    home = os.path.expanduser("~")
    if "ERGO_API_KEY" in os.environ:
        apikey = os.environ["ERGO_API_KEY"]
    elif os.path.exists(os.path.join(home, ".ergo_api_key")):
        with open(os.path.join(home, ".ergo_api_key")) as fh:
            apikey = fh.read().rstrip()
    else:
        sys.stderr.write("Missing ERGO API Key.\nPlease generate one at https://ergo.igenbio.com/#!/settings.\n")
        text = input("ERGO API Key:")
        apikey = str(text)
        if os.path.exists(os.path.join(home)):
            with open(os.path.join(home, ".ergo_api_key"), "w") as fh:
                fh.write(apikey)
    
    if "ERGO_HOST" in os.environ:
        eh = os.environ["ERGO_HOST"]
        if len(eh) > 0:
            ERGO_HOST = eh
    if "ERGO_URL" in os.environ:
        eu = os.environ["ERGO_URL"]
        if len(eu) > 0:
            ERGO_URL = eu

    ergo = ERGO(apikey)
