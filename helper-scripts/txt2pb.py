"""
Convert a word list (i.e. a plain text file with one item per line) to a
pickle dump of a list of words, so the text file doesn't have to be
converted first on later occasions
"""
import argparse
import pickle
import sys
import os

cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", required=True, help="File")
cli.add_argument("-l", "--lowercase", default=False, help="Convert to lower case?")
args = cli.parse_args()

if not os.path.exists(args.input):
	print("File not found.")
	sys.exit(1)

words = set()
print("Reading...")
with open(args.input) as input:
	while True:
		line = input.readline()
		if line == "":
			break

		word = line.strip()
		if args.lowercase:
			word = word.lower()

		words.add(word)

print("Writing...")
with open(".".join(args.input.split(".")[:-1]) + ".pb", "wb") as output:
	pickle.dump(words, output)

print("Done.")