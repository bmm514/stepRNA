#!/usr/bin/env python3

#Python Modules
import numpy as np
from subprocess import run, PIPE
import os
import sys
from collections import defaultdict
import csv

#Modules from this package
from stepRNA.general import mini_maxi, replace_ext, check_dir
from stepRNA.processing import make_unique, rm_ref_matches, sam_to_bam
from stepRNA.commands import left_overhang, right_overhang
from stepRNA.output import make_csv, make_type_csv, write_to_bam, print_hist

#My scripts...
from bin import remove_exact
from bin import run_bowtie

#Modules that need to be installed
try:
    from Bio import SeqIO
except ImportError:
    print('Error: Biopython not found, can be installed with\npip3 install biopython', file=sys.stderr)
    sys.exit(1)

try:
    import pysam
except ImportError:
    print('Error: Pysam not found, can be installed with\npip3 install pysam', file=sys.stderr)
    sys.exit(1)

#Set-up arguments...
from argparse import ArgumentParser, SUPPRESS

parser = ArgumentParser(description='Align an reference RNA file to read sequences.\n Output will be a set of CSV files containing information about the length of the reads, number of reads aligned to a reference sequence and the length of overhangs of the alignment. \n Reference RNA file will be automatically indexed', add_help=False)

optional = parser.add_argument_group('Optional Arguments')
required = parser.add_argument_group('Required Arguments')
flags = parser.add_argument_group('Flags')

#Add back help...
optional.add_argument(
    '-h',
    '--help',
    action='help',
    default=SUPPRESS,
    help='show this help message and exit'
)

required.add_argument('-r', '--reference', help='Path to the reference seqeunces', required=True)
required.add_argument('-q', '--reads', help='Path to the read sequences', required=True)
optional.add_argument('-n', '--name',  help='Prefix for the output files')
optional.add_argument('-d', '--directory', default = os.curdir, help='Directory to store the output files')
optional.add_argument('-m', '--min_score', default=-1, type=int, help='Minimum score to accept, default is the shortest read length')
flags.add_argument('-e', '--remove_exact', action='store_true', help='Remove exact read matches to the reference sequence')
flags.add_argument('-u', '--make_unique', action='store_true', help='Make FASTA headers unique in reference and reads i.e. >Read_1 >Read_2')

parser._action_groups.append(optional)
parser._action_groups.append(flags)

args = parser.parse_args()

# Parse arguments...
ref = args.reference
reads = args.reads
min_score = args.min_score
outdir = check_dir(args.directory)
if args.name is None:
    filename = os.path.splitext(reads)[0] 
else:
    filename = args.name

#Join together output directory and filename to make a prefix...
prefix = os.path.join(outdir, filename)
print(prefix)

#Remove exact matches to reference if set...
if args.remove_exact:
    remove_exact.main(ref, reads)

#Make unique headers if set...
if args.make_unique:
    reads = make_unique(reads)
    reads = make_unique(ref)

#Build a reference (suppress verbosity)...
ref_base = os.path.splitext(ref)[0]
command = 'bowtie2-build {} {}'.format(ref, ref_base)
command = command.split()
run(command, stdout=PIPE)

# Set min_score if not present, else set as match bonus * min_score...
minimum, maximum = mini_maxi(reads, file_type = 'fasta')
print('Miniumum sequence length in {}: {}'.format(os.path.basename(reads), minimum))
print('Maxiumum sequence length in {}: {}'.format(os.path.basename(reads), maximum))

if min_score != -1:
    min_score = 3 * min_score
else:
    min_score = 3 * minimum 


# Run bowtie command...
sam_file = replace_ext(prefix, '.sam')
command = ['bowtie2', '-x', ref_base, '-U', reads, '-f', '-N', '0', '-L', '10', '--no-1mm-upfront', '--nofw','--local', '--ma', '3', '--mp', '{},{}'.format(maximum, maximum), '--score-min', 'L,{},0'.format(min_score), '-S', sam_file]

bowtie = run(command)
#Convert sam to bam...
sorted_bam = sam_to_bam(sam_file)

#Count overhangs...
bam_in = pysam.AlignmentFile(sorted_bam, 'rb')
right_dic = defaultdict(lambda:0)
left_dic = defaultdict(lambda:0)
type_dic = defaultdict(lambda:0)
read_len_dic = defaultdict(lambda:0)
refs_read_dic = defaultdict(lambda:0)
for name in bam_in.references:
    refs_read_dic[name] = 0

for line in bam_in:
    if line.cigarstring != None:
        if ('D' or 'I') not in line.cigarstring:
            ref_pos = line.get_reference_positions(full_length = True)
            try:
                right, right_type = right_overhang(bam_in, line, ref_pos)
                left, left_type = left_overhang(bam_in, line, ref_pos)
                # Create dictionaries to sort information...
                right_dic[right] += 1 # right overhang count
                left_dic[left] += 1 # left overhang count
                type_dic[left_type + '_' + right_type] += 1 # type of overhang count
                read_len_dic[line.query_length] += 1 # read length count
                refs_read_dic[line.reference_name] += 1 # number of reads algining to reference
                write_to_bam(line, left_type, right_type, prefix=prefix) # separate reads to 'bam' files
            except Exception:
                continue

#Put overhangs infomation into a csv and print to terminal...
print('\n## Overhang counts ##')
make_csv([right_dic, left_dic], prefix + '_overhang.csv', ['OH','Left','Right'])
print('\n## Overhang types ##')
make_type_csv(type_dic, prefix + '_type.csv', ['OH_type', 'count'])
print('\n## Read lengths ##')
make_type_csv(read_len_dic, prefix + '_read_len.csv', ['Read_length', 'count'], sort=True)
make_type_csv(refs_read_dic, prefix + '_ref_hits.csv', ['Reference', 'count'], show=False)
print()
with open(prefix + '_overhang.csv') as summary:
    left_dens = []
    right_dens = []
    left_tot = 0
    right_tot = 0
    keys = []
    csv_reader = csv.reader(summary, delimiter=',')
    head = next(csv_reader)
    for line in csv_reader:
        keys.append(line[0])
        left_dens.append(int(line[1]))
        left_tot += int(line[1])
        right_dens.append(int(line[2]))
        right_tot += int(line[2])


for key in range(len(keys)):
    left_dens[key] = 100 * left_dens[key] / left_tot
    right_dens[key] = 100 * right_dens[key] / right_tot
    
#Print histogram of overhangs to terminal...
print('Left Handside Overhang Histogram')
print_hist(left_dens, keys)

print('Right Handside Overhang Histogram')
print_hist(right_dens, keys)