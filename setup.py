#!/usr/bin/env python
#
# This is the setup script for Rubber. It acts both as a part of the
# configuration script � la autoconf and as a setup script � la Distutils.
#
# As the rest of Rubber, this script is covered by the GPL (see COPYING).
# (c) Emmanuel Beffara, 2002

import re
import string
import sys

# The module `settings' is produced by the configuration script.

try:
	import settings
except ImportError:
	pass

###  system checking

def do_check ():
	"""
	Check that everything required for Rubber is present.
	"""
	print "The configure script is running, good."
	try:
		import distutils.core
		print "The Distutils are installed, good."
	except ImportError:
		print """
I could not import distutils.core. You need the Distutils to install Rubber.
(You don't need them to run Rubber, so you can try configuring and installing
it by hand if you are brave.)"""
		return 1
	return 0


###  substitution of variables in files

def expand_vars (subst, str):
	"""
	Substitute all occurences of the pattern ${foo} in the string with the
	value of the key associated key in the dictionary `subst' until there are
	no such patterns any more.
	"""
	pattern = re.compile("\${(" + string.join(subst.keys(), "|") + ")}")
	def repl (match, subst=subst):
		return subst[match.group(1)]
	str2 = pattern.sub(repl, str)
	while str != str2:
		str = str2
		str2 = pattern.sub(repl, str)
	return str

def make_files (subst, files):
	"""
	Apply the given substitution (passed as a dictionary) in the specified
	files. The list enumerates the target files, for each target `foo' the
	source is named `foo.in' using standard convention. The convention for
	substitutions is the following:
	- @bar@ --> sub['bar']
	- @@quux@@ --> sub['quux']
	  where all '${xyz}' are replaced by sub['xyz'] recursively
	"""
	import re
	import string

	words = string.join(subst.keys(), "|")
	pat1 = re.compile("@(" + words + ")@")
	pat2 = re.compile("@@(" + words + ")@@")

	def repl (match, subst=subst):
		return subst[match.group(1)]
	def full_repl (match, subst=subst):
		return expand_vars(subst, subst[match.group(1)])

	for file in files:
		print "writing %s..." % file
		input = open(file + ".in")
		output = open(file, "w")
		for line in input.readlines():
			output.write(pat1.sub(repl, pat2.sub(full_repl, line)))
		input.close()
		output.close()


###  distutils setup

def do_setup ():
	"""
	Run the setup() function from the distutils with appropriate arguments.
	"""
	from distutils.core import setup
	try:
		mandir = expand_vars(settings.sub, settings.sub["mandir"])
	except NameError:
		mandir = "man"
	setup(
		name = "rubber",
		version = settings.sub["version"],
		description = "The Rubber system for building LaTeX documents",
		long_description = """\
This is a building system for LaTeX documents. It is based on a routine that
runs (hopefully) just as many compilations as necessary. The module system
provides a great flexibility that virtually allows support for any package
with no user intervention, as well as pre- and post-processing of the
document.""",
		author = "Emmanuel Beffara",
		author_email = "emmanuel@beffara.org",
		url = "http://beffara.org/stuff/rubber.html",
		licence = "GPL",
		packages = ["rubber", "rubber.modules"],
		package_dir = {"rubber": "src"},
		scripts = ["rubber"],
		data_files =
		[(mandir + "/man1", ["man/en/rubber.1"]),
		 (mandir + "/fr/man1", ["man/fr/rubber.1"])]
		)


###  command line

# This is mainly the standard command line from the distutils, except that we
# add specific commands for the configure script, namely:
# - `check' for checking if the system is appropriate
# - `config' to generate configuration-specific files
# - `inst' to install the package according to the configuration's settings
#          (here, the install prefix is the next argument)

if len(sys.argv) > 1:
	cmd = sys.argv[1]
	if cmd == "check":
		ret = do_check()
		sys.exit(ret)
	elif cmd == "config":
		sub = settings.sub
		make_files(sub, ["Makefile", "rubber", "src/version.py"])
		print ("""\
Rubber is now configured. It will be installed in the following directories:
    the main script: %s
    the modules:     %s
    the man pages:   %s
(unless you specify otherwise when running `make install')""" %
		(expand_vars(sub, sub["bindir"]),
		 expand_vars(sub, sub["moddir"]),
		 expand_vars(sub, sub["mandir"])))
	elif cmd == "inst":
		sub = settings.sub
		sub["prefix"] = sys.argv[2]
		del sys.argv[2]
		sys.argv = sys.argv + [
			"--prefix", sub["prefix"],
			"--install-lib", expand_vars(sub, sub["moddir"]),
			"--install-scripts", expand_vars(sub, sub["bindir"])]
		sys.argv[1] = "install"
		do_setup()
	else:
		do_setup()
else:
	do_setup()