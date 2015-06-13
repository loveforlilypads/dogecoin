#!/usr/bin/python
#
# linearize-data.py: Construct a linear, no-fork version of the chain.
#
# Copyright (c) 2013 The Bitcoin developers
# Distributed under the MIT/X11 software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#

import json
import struct
import re
import base64
import httplib
import sys
import hashlib
import datetime

settings = {}


def uint32(x):
	return x & 0xffffffffL

def bytereverse(x):
	return uint32(( ((x) << 24) | (((x) << 8) & 0x00ff0000) |
		       (((x) >> 8) & 0x0000ff00) | ((x) >> 24) ))

def bufreverse(in_buf):
	out_words = []
	for i in range(0, len(in_buf), 4):
		word = struct.unpack('@I', in_buf[i:i+4])[0]
		out_words.append(struct.pack('@I', bytereverse(word)))
	return ''.join(out_words)

def wordreverse(in_buf):
	out_words = []
	for i in range(0, len(in_buf), 4):
		out_words.append(in_buf[i:i+4])
	out_words.reverse()
	return ''.join(out_words)

def calc_hdr_hash(blk_hdr):
	hash1 = hashlib.sha256()
	hash1.update(blk_hdr)
	hash1_o = hash1.digest()

	hash2 = hashlib.sha256()
	hash2.update(hash1_o)
	hash2_o = hash2.digest()

	return hash2_o

def calc_hash_str(blk_hdr):
	hash = calc_hdr_hash(blk_hdr)
	hash = bufreverse(hash)
	hash = wordreverse(hash)
	hash_str = hash.encode('hex')
	return hash_str

def get_blk_dt(blk_hdr):
	members = struct.unpack("<I", blk_hdr[68:68+4])
	dt = datetime.datetime.fromtimestamp(members[0])
	dt_ym = datetime.datetime(dt.year, dt.month, 1)
	return dt_ym

def get_block_hashes(settings):
	blkindex = []
	f = open(settings['hashlist'], "r")
	for line in f:
		line = line.rstrip()
		blkindex.append(line)

	print("Read " + str(len(blkindex)) + " hashes")

	return blkindex

def mkblockset(blkindex):
	blkmap = {}
	for hash in blkindex:
		blkmap[hash] = True
	return blkmap

def copydata(settings, blkindex, blkset):
	inFn = 0
	inF = None
	outFn = 0
	outsz = 0
	outF = None
	blkCount = 0

	lastDate = datetime.datetime(2000, 1, 1)
	timestampSplit = False
	fileOutput = True
	maxOutSz = settings['max_out_sz']
	if 'output' in settings:
		fileOutput = False
	if settings['split_timestamp'] != 0:
		timestampSplit = True

	while True:
		if not inF:
			fname = "%s/blk%05d.dat" % (settings['input'], inFn)
			print("Input file" + fname)
			inF = open(fname, "rb")

		inhdr = inF.read(8)
		if (not inhdr or (inhdr[0] == "\0")):
			inF.close()
			inF = None
			inFn = inFn + 1
			continue

		inMagic = inhdr[:4]
		if (inMagic != settings['netmagic']):
			print("Invalid magic:" + inMagic)
			return
		inLenLE = inhdr[4:]
		su = struct.unpack("<I", inLenLE)
		inLen = su[0]
		rawblock = inF.read(inLen)
		blk_hdr = rawblock[:80]

		hash_str = calc_hash_str(blk_hdr)
		if not hash_str in blkset:
			print("Skipping unknown block " + hash_str)
			continue

		if blkindex[blkCount] != hash_str:
			print("Out of order block.")
			print("Expected " + blkindex[blkCount])
			print("Got " + hash_str)
			sys.exit(1)

		if not fileOutput and ((outsz + inLen) > maxOutSz):
			outF.close()
			outF = None
			outFn = outFn + 1
			outsz = 0

		if timestampSplit:
			blkDate = get_blk_dt(blk_hdr)
			if blkDate > lastDate:
				print("New month " + blkDate.strftime("%Y-%m") + " @ " + hash_str)
				lastDate = blkDate
				if outF:
					outF.close()
					outF = None
					outFn = outFn + 1
					outsz = 0

		if not outF:
			if fileOutput:
				fname = settings['output_file']
			else:
				fname = "%s/blk%05d.dat" % (settings['output'], outFn)
			print("Output file" + fname)
			outF = open(fname, "wb")

		outF.write(inhdr)
		outF.write(rawblock)
		outsz = outsz + inLen + 8

		blkCount = blkCount + 1

		if (blkCount % 1000) == 0:
			print("Wrote " + str(blkCount) + " blocks")

if __name__ == '__main__':
	if len(sys.argv) != 2:
		print "Usage: linearize-data.py CONFIG-FILE"
		sys.exit(1)

	f = open(sys.argv[1])
	for line in f:
		# skip comment lines
		m = re.search('^\s*#', line)
		if m:
			continue

		# parse key=value lines
		m = re.search('^(\w+)\s*=\s*(\S.*)$', line)
		if m is None:
			continue
		settings[m.group(1)] = m.group(2)
	f.close()

	if 'netmagic' not in settings:
		settings['netmagic'] = 'c0c0c0c0'
	if 'genesis_hash' not in settings:
		settings['genesis_hash'] = '1a91e3dace36e2be3bf030a65679fe821aa1d6ef92e7c9902eb318182c355691'
	if 'input' not in settings:
		settings['input'] = 'input'
	if 'hashlist' not in settings:
		settings['hashlist'] = 'hashlist.txt'
	if 'split_timestamp' not in settings:
		settings['split_timestamp'] = 0
	if 'max_out_sz' not in settings:
		settings['max_out_sz'] = 1000L * 1000 * 1000

	settings['max_out_sz'] = long(settings['max_out_sz'])
	settings['split_timestamp'] = int(settings['split_timestamp'])
	settings['netmagic'] = settings['netmagic'].decode('hex')

	if 'output_file' not in settings and 'output' not in settings:
		print("Missing output file / directory")
		sys.exit(1)

	blkindex = get_block_hashes(settings)
	blkset = mkblockset(blkindex)

	if not settings['genesis_hash'] in blkset:
		print("not found")
	else:
		copydata(settings, blkindex, blkset)


