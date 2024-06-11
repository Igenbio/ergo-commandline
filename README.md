# Setting up the application
1. [Download](https://github.com/Igenbio/ergo-commandline/releases) a release.
2. After downloading the application you'll need to open a terminal window. (Applications > Utilities > Terminal on Mac, for example). 
3. Navigate to the directory that the 'ergo' application is installed (e.g. cd ~/Downloads).
4. Set the permissions to execute (chmod +x ergo)
5. Run the ergo command. (./ergo)

## MacOS

### On MacOS you may be prompted that the application cannot be checked for malicious software. In order to be able to run the application you'll need to allow it in System Preferences > Security & Privacy > General. There will be a section on the bottom saying "ergo" was blocked from running. You'll need to click "Allow Anyway".

### More details from Apple [here](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unidentified-developer-mh40616/11.0/mac/11.0).


# Setup the API Key.

## After the application can run, you'll be prompted for an API key. You'll need to set this up in ERGO. 
1. Log into ERGO and go [settings](https://ergo.igenbio.com/#!/settings).  
2. Scroll down to "API KEYS". Click on "Create API Key". "Issued To" and "Note" should be "ergo", leave "scope" set to "User" (unless you need or have full account permissions.)
3. Click create.
4. Copy the 'Token' (Be sure to copy all of the text - it is a long string.)
5. Paste it into the ERGO Command where it says "ERGO API Key:"
6. Press enter.

```
$ ergo projects list
Missing ERGO API Key.
Please generate one at https://ergo.igenbio.com/#!/settings.
ERGO API Key:PASTE KEY HERE
```

The 'ergo' commmand should work now. Test it by running 'ergo projects list'. This should give a list of all projects on your account. 


# Downloading files from a project in ERGO using the 'ergo' tool.

1. Locate the Id of the project from which you wish download. Project Ids are "UUIDs" - and are hexadecimal numbers separated by dashes. You can list all project ids, names, and descriptions by issuing the command "ergo projects list". The Project ID is the first column (e.g. 02f7c552-2bd2-469a-812e-704c526ad89d).
2. Get the info about the project you wish to download: 
```
$ ergo project info -i d3b0ed11-614f-42bf-b523-b4d0f6fda00c
Id:     d3b0ed11-614f-42bf-b523-b4d0f6fda00c
Name:   **Amplicon Test**
Description:
Date Created:   2020-07-22T14:12:53.323231-05:00
Size:   38.1MB
Permissions:
                         Email          Permission
              user@IGENBIO.com                read
Files:
                          Type              Number
                          biom                   4
                      fastq.gz                  10
                          .nwk                   4
                         fasta                   8
                           txt                   4
                          html                   1
```
3. Downloading from a project.
```
usage: ergo project download [-h] -i ID [-f FILTER [FILTER ...]] [-r {ergo_id,ergo_name,sample_name}]

optional arguments:
  -h, --help            show this help message and exit
  -i ID, --id ID        Id of project to download from.
  -f FILTER [FILTER ...], --filter FILTER [FILTER ...]
                        Filter elements by extension (e.g. fastq.gz)
  -r {ergo_id,ergo_name,sample_name}, --rename {ergo_id,ergo_name,sample_name}
                        Set the name of files by this choice.
```
For example, to download all the read files from the above project we would use the command:
```
ergo project download -i d3b0ed11-614f-42bf-b523-b4d0f6fda00c -f fastq.gz -r sample_name
```
- -i specifies the ID of the project
- -f to filter by type of "fastq.gz"
- -r to rename files that are downloaded by ERGO's sample name.

Please Note: If there is no sample name, ERGO's filename will be used.

# Uploading reads to a project in ERGO
```
usage: ergo reads [-h] -1 FIRST [FIRST ...] [-2 SECOND [SECOND ...]] [-o {fr,rf,ff}] [--interleaved] [-p PROJECT] [-g GENOME] [-s] [-a]

optional arguments:
  -h, --help            show this help message and exit
  -1 FIRST [FIRST ...], --first FIRST [FIRST ...]
                        List of Reads to Add to ERGO.
  -2 SECOND [SECOND ...], --second SECOND [SECOND ...]
                        List of Read pairs to Add to ERGO.
  -o {fr,rf,ff}, --orientation {fr,rf,ff}
                        Orientation of read pairs.
  --interleaved         Reads are interleaved
  -p PROJECT, --project PROJECT
                        Id of project to add this element to, or "new" to create a new project.
  -g GENOME, --genome GENOME
                        Short name of Genome to associate with element.
  -s, --silent          No Output, except on error.
  -a, --auto-meta       Attempt to auto detect sample name from file name.
```

## Notes

Both `-1` and `-2` parameters can use globs e.g. `*R1_fastq.gz`. Using the `-a` option is recommended to get the expected sample names.
You should not need to use `-o` unless it is an unusual read configuration. The `fr` orientation is the default. 
You can find the genome "short name" by querying the list of genomes accesible to you (`ergo genomes list`).

## Example

`ergo reads -p ddfa440c-cca9-42de-b521-4fa8f75ce2fb -1 *R1_001.fastq.gz -2 *R2_001.fastq.gz -g EC -a`

# Projects

## Creating a new project
```
usage: ergo project create [-h] -n NAME [-d DESCRIPTION] [-p PERMISSIONS [PERMISSIONS ...]]

optional arguments:
  -h, --help            show this help message and exit
  -n NAME, --name NAME  Project Name
  -d DESCRIPTION, --description DESCRIPTION
                        Project Descriptions
  -p PERMISSIONS [PERMISSIONS ...], --permissions PERMISSIONS [PERMISSIONS ...]
                        List of user email addresses and their permission. e.g. example@igenbio.com:manage. Possible permissions are read,
                        write, manage.
```

### Notes
Only `-n`/`--name` is required. The id of project will be output after project creation.

## Viewing detailing about a project
```
usage: ergo project info [-h] -i ID [-f] [-l] [-t TYPE]

optional arguments:
  -h, --help            show this help message and exit
  -i ID, --id ID        Id of project to get info about.
  -f, --files           Show only files on project.
  -l, --long            Long view for files on project
  -t TYPE, --type TYPE  Show files only of this type.
```

### Notes
The `-f` flag will list the ids of the files attached to the project and `-l` will list names and file types. You can filter the returned files with `-t`. The lower case file extension is the expected input. For example, for reads use `fastq.gz`.

## Deleting a project
`ergo project delete`

### Notes
At the moment this will ophan any resources attached to the project (experiments, files, etc)

# Manging Files

## Listing files on your account
`ergo files list`

### Notes
This will list all files on your account. However, please avoid using it as it is slow to recover everything you have access to.

## Adding Files
```
usage: ergo files add [-h] -f FILES [FILES ...] [-g GENOME] [-p PROJECT] [-s]

optional arguments:
  -h, --help            show this help message and exit
  -f FILES [FILES ...], --files FILES [FILES ...]
                        Files to add to ERGO.
  -g GENOME, --genome GENOME
                        Short name of Genome to associate with element.
  -p PROJECT, --project PROJECT
                        Id of project to add this element to.
  -s, --silent          No Output, except on error.
```

### Notes
This is a generic way to add files to ERGO. For read files it is suggested that you use `ergo reads` as it correctly sets the metadata for read files. At the moment, this method won't set the file type in ERGO, so this is something you will have to do manually from the file page in ERGO. Tagging the genome (`-g`) is essential for some files like `.bam` to be associated correctly with the genome and displayed in the genome browser.

## Deleting Files
```
usage: ergo files delete [-h] [-s] id

positional arguments:
  id            Id of element to delete.

optional arguments:
  -h, --help    show this help message and exit
  -s, --silent  No Output, except on error.
```

### Notes
This permanently deletes files from ERGO. There is no confirmation.

## Downloading Files

There are a few ways to download files.

1. Directly `ergo files download`
2. From a project `ergo project download`
3. From a workflow `ergo workflows download`

# Managing Workflows 
### (Please check your license to see if it supports managing workflows from the API.)

## Listing workflows
`ergo workflows list`

### Notes
This will list every workflow that belongs to your user. At the moment you can only list workflows that belong to your user.

## Viewing more information about a workflow
```
$ ergo workflows details -i 5a691e0b-d47f-42e9-9fad-c3e884a603f5
Id: 5a691e0b-d47f-42e9-9fad-c3e884a603f5
User: {'email_address': 'user@IGENBIO.com', 'name': 'User'}
Display Name: Variant Analysis
Description: Aligns fastq files against reference, then calls variants.
Status: COMPLETED
Completion: 48 of 48 steps complete.
Steps:
	Number	Name	Status
	1	QC Reads	COMPLETED
	1	QC Reads	COMPLETED
  --  --
```

### Notes 
This will display information about the workflow in human-readable format. Add `--json` to get the raw format.

## Deleting a workflow
`ergo workflows delete [-h] -i ID`

### Notes
This will delete a workflow. A warning: No confirmation is required and deletions are permanent. Deletions will also free the resouces (files) associated with the workflow, like output files. All input files are unaffected.

## Starting/Stopping a workflow
`ergo workflows stop` or `ergo workflows start`

## Creating a workflow

1. First list the workflows that you have access to: `ergo workflows create list`
2. Next, save the parameter template file `ergo workflows create params <workflow_name> > params.json`
3. Then edit the parameters file to setup the parameters you want for the job.
4. Then create the workflow `ergo workflows create new --params <params_file> --project-id <project>`

## Adding files to a workflow

Add files to the workflow using `ergo workflows update` and supplying a list of file ids.
