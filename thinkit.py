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
	if 'Regex declarations':
		# Importing.
		x_import = re.compile(r'^\s*@import(?P<flag>\S+)?\s+(?P<files>\S+\s*(,\s*\S+\s*)*)$')
		# Macros.
		x_macro      = re.compile(r'^\s*@(?P<name>\w+)\(\s*(?P<params>\w+\s*(,\s*\w+\s*)*)\)\s*{\s*$')
		x_macro_call = re.compile(r'^\s*@(?P<name>\w+)\(\s*(?P<params>\S+\s*(,\s*\S+\s*)*)\)\s*;?\s*$')
		x_macro_end  = re.compile(r'^\s*}\s*(#.*)?$')
		# Comment block.
		x_if = re.compile(r'^\s*@if(?P<flag>\S+)?\s+(?P<val>0|1|true|false|(no)?import)\s*$')
		x_endif = re.compile(r'^\s*@@\s*$')
		# Main method input output... how silly.
		x_main = re.compile(r'^\s*@main(\s+(?P<func>\S+))?\s*$')
		x_endmain = re.compile(r'^\s*@endmain\s*$')
		# Line replacements.
		x_plot = re.compile(r'^(\s*)plot(\s+)')
		x_input = re.compile(r'^(\s*)input(\s+)')
		# Keep track of script starts.
		x_script = re.compile(r'^\s*script\s+(?P<name>\S+)\s*{\s*(#.*)?$')
	if 'Post-loop actions':
		# NOTE: These shouldn't be recursive, so they don't need to drop into imports
		latest_script = None
		main_block = []
		main_block_name = None
		main_block_active = False
	try:
		while True:
			line = next(it)
			if main_block_active:
				if x_endmain.search(line):
					main_block_active = False
					continue
				main_block.append(line)
			
			# if @import, run process() against target file
			m = x_import.search(line)
			if m:
				# Don't import inside a main block.
				if main_block_active:
					raise 'some kind of fuss'
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
			
			# if a script start, then jot it down.
			m = x_script.search(line)
			if m:
				latest_script = m.group('name')
			
			# if main, take the main block and dump out at the end of the file if not importing
			m = x_main.search(line)
			if m:
				main_block_active = True
				# Assign script/function for main block to call, or set it to script name.
				mname = m.group('func')
				if mname:
					main_block_name = mname
				main_block_name = main_block_name or latest_script
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
	if main_block and main_block_name and not importing:
		yield ''
		innames = []
		for s in main_block:
			# collect inputs...
			m = re.search(r'^\s*input\s+(\S+)\s*=.*$',s)
			if m and m.group(1):
				innames.append(m.group(1))
			yield re.sub(r'^\s*','',s)
		#varname = re.sub(r'.*(\\|/)(?P<name>[^\\/]+)(\..*)?$',r'\g<name>',__name__)
		varname = main_block_name
		params = ','.join(innames)
		yield f'\nplot z_{varname} = {main_block_name}({params});'

if __name__ == '__main__':
	for s  in process(fiter(sys.stdin)):
		print(s)

