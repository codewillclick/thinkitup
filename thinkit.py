#!/bin/env python

import os
import re
import sys
import os.path

def fiter(f):
	for s in f:
		yield re.sub(r'\r?\n$','',s)

# Match the line, first, then insert an iteration if needed before moving on.

def process(src,imported=None,macros=None,show=False,importing=False,noplot=False,noinput=False):
	imported = imported or set()
	macros = macros or {}
	show_macros = show
	it = iter(src)
	# Regex declarations ahead of time.
	# Importing.
	x_import = re.compile(r'^\s*@import(?P<flag>\S+)?\s+(?P<files>\S+\s*(,\s*\S+\s*)*)$')
	# Macros.
	x_macro      = re.compile(r'^\s*@(?P<name>\w+)\(\s*(?P<params>\w+\s*(,\s*\w+\s*)*)\)\s*{\s*$')
	x_macro_call = re.compile(r'^\s*@(?P<name>\w+)\(\s*(?P<params>\S+\s*(,\s*\S+\s*)*)\)\s*;?\s*$')
	x_macro_end  = re.compile(r'^\s*}\s*(#.*)?$')
	# Comment block.
	x_if = re.compile(r'^\s*@if(?P<flag>\S+)?\s+(?P<val>0|1|true|false|(no)?import)\s*$')
	x_endif = re.compile(r'^\s*@@\s*$')
	# Line replacements.
	x_plot = re.compile(r'^(\s*)plot(\s+)')
	x_input = re.compile(r'^(\s*)input(\s+)')
	try:
		while True:
			line = next(it)
			# if @import, run process() against target file
			m = x_import.search(line)
			if m:
				fr = [s.strip() for s in m.group('files').split(',')]
				flag = m.group('flag') or ''
				# ^ flags...
				# '?', leave plots alone, don't pass the noplot flag
				for fname in fr:
					if fname in imported:
						continue
					try:
						with open(f'{fname}.ts','r') as f:
							no_plots  = True if '?' in flag else False # '?', leave the plots be
							no_inputs = True if '!' in flag else False # '!', leave inputs be
							for s in process(fiter(f),imported,macros,show,
									importing=True,
									noplot=noplot or no_plots,
									noinput=noinput or no_inputs):
								yield s
					finally:
						imported.add(fname) # make sure there are no re-imports
				continue

			# if @<macro>(...){}, read in lines and store macro
			m = x_macro.search(line)
			if m:
				macro = m.group('name')
				pr = [s.strip() for s in m.group('params').split(',')]
				try:
					# Actually process the macro, borrowing main iterator.
					if show_macros:
						yield '#'+line
					sr = []
					while True:
						s = next(it)
						if show_macros:
							yield '#'+s
						if x_macro_end.match(s):
							break
						# Sort by reverse str len to get around params that are
						# substrings of each other, but without losing index position
						# in the pr list.
						prz = sorted(zip(pr,range(len(pr))),key=lambda r:-len(r[0]))
						for p,i in prz:
							s = re.sub(f'@{p}','%%(%i)s' % i,s)
						sr.append(s)
					macros[macro] = '\n'.join(sr)
				except StopIteration:
					print(f'ERROR: broke macro definition ({macro}) with EOF',file=sys.stderr)
				continue
			
			# TODO: Run macro replacement lines through process() as well, so we can have
			#   macros inside of macros inside of macros inside of...
			# TODO: Make macros string-replacements, rather than line-replacements.
			# if @<macro>(...), yield convered macro lines
			m = x_macro_call.search(line)
			if m:
				macro = m.group('name')
				pr = [s.strip() for s in m.group('params').split(',')]
				#print('macros',macro,macros[macro])
				yield macros[macro] % {str(i):s for s,i in zip(pr,range(len(pr)))}
				continue
			
			# if @if... @@, comment all that junk out
			m = x_if.search(line)
			if m:
				val = m.group('val')
				val = {
					'1':True,
					'true':True,
					'0':False,
					'false':False,
					'import':importing,
					'noimport':not importing
				}[val]
				flag = m.group('flag') or ''
				try:
					while True:
						s = next(it)
						if x_endif.search(s) or val:
							raise StopIteration()
						if not val:
							if not '?' in flag:
								# (yield nothing if flag is raised)
								yield '# '+s
				except StopIteration:
					continue

			# if a random endif, just... ignore it I guess; only @if cares
			if x_endif.search(line):
				continue
			
			# TODO: Replacing the last plot in a script {} is a no-no.
			# otherwise just yield the line
			if noplot and re.search(x_plot,line):
				line = re.sub(x_plot,r'\1'+'def'+r'\2',line,re.IGNORECASE)
			if noinput and re.search(x_input,line):
				line = re.sub(x_input,r'\1'+'def'+r'\2',line,re.IGNORECASE)
			yield line
	except StopIteration:
		pass

if __name__ == '__main__':
	for s  in process(fiter(sys.stdin)):
		print(s)

