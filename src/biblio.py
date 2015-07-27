# This file is part of Rubber and thus covered by the GPL
# Sebastian Kapfer <sebastian.kapfer@fau.de> 2015.
# based on code by Sebastian Reichel and others.
# vim: noet:ts=4
"""
Bibliographies (Biber and BibTeX).
"""

from rubber.util import _, msg
import rubber.util
from rubber.depend import Shell
import os, os.path
from os.path import exists, getmtime, join
import re
import string
import sys

# TODO: merge these classes if it makes sense.

def find_resource (name, suffix="", environ_path=None):
	"""
	find the indicated file, mimicking what latex would do:
	tries adding a suffix such as ".bib",
	or looking in paths (set environ_path to things like "BIBINPUTS")
	if unsuccessful, returns None.
	"""
	from_environ = []
	if environ_path is not None:
		environ_path = os.getenv (environ_path)
		if environ_path is not None:
			from_environ = environ_path.split (":")

	for path in [ "." ] + from_environ:
		fullname = os.path.join (path, name)
		if os.path.exists (fullname):
			return fullname
		elif suffix != "" and os.path.exists (fullname + suffix):
			return fullname + suffix

	msg.warn (_("cannot find %s") % name, pkg="find_resource")
	return None

class BibTool (Shell):
	"""
	Shared code between bibtex and biber support.
	"""
	def __init__ (self, set, doc, tool):
		self.doc = doc
		assert tool in [ "biber", "bibtex" ]
		self.tool = tool
		Shell.__init__ (self, set, command=[ None, doc.basename () ])
		for suf in [ ".bbl", ".blg", ".run.xml" ]:
			self.add_product (doc.basename (with_suffix=suf))

	def add_bib_resource (self, doc, opt, name):
		"""new bib resource discovered"""
		msg.log (_("bibliography resource discovered: %s" % name), pkg="biblio")
		options = rubber.util.parse_keyval (opt)

		# If the file name looks like it contains a control sequence
		# or a macro argument, forget about this resource.
		if name.find('\\') > 0 or name.find('#') > 0:
			return

		# skip Biber remote resources
		if "location" in options and options["location"] == "remote":
			return

		filename = find_resource (name, suffix=".bib", environ_path="BIBINPUTS")
		if filename is None:
			msg.error (_ ("cannot find bibliography resource %s") % name, pkg="biblio")
		else:
			self.add_source (filename)

	def add_bibliography (self, doc, names):
		for bib in names.split (","):
			self.add_bib_resource (doc, None, bib.strip ())

	def run (self):
		# check if the input file exists. if not, refuse to run.
		if not os.path.exists (self.sources[0]):
			msg.info (_("Input file for %s does not yet exist.") % self.tool, pkg="biblio")
			return True
		# command might have been updated in the mean time, so get it now
		# FIXME make tool configurable
		self.command[0] = self.tool
		if Shell.run (self):
			return True
		msg.warn (_("There were errors running %s.") % self.tool, pkg="biblio")
		return False

class BibTeX (BibTool):
	"""Node: make .bbl from .aux using BibTeX"""
	def __init__ (self, set, doc):
		BibTool.__init__ (self, set, doc, "bibtex")
		doc.hook_macro ("bibliography", "a", self.add_bibliography)
		self.add_source (doc.basename (with_suffix=".aux"), track_contents=True)
		doc.add_product (doc.basename (with_suffix="-blx.bib"))
		doc.add_source (doc.basename (with_suffix=".bbl"), track_contents=True)

	def run (self):
		# strip abspath, to allow BibTeX to write the bbl.
		self.command[1] = os.path.basename (self.sources[0])
		return BibTool.run (self)

class Biber (BibTool):
	"""Node: make .bbl from .bcf using Biber"""
	def __init__ (self, set, doc):
		BibTool.__init__ (self, set, doc, "biber")
		for macro in ("addbibresource", "addglobalbib", "addsectionbib"):
			doc.hook_macro (macro, "oa", self.add_bib_resource)
		doc.hook_macro ("bibliography", "a", self.add_bibliography)
		self.add_source (doc.basename (with_suffix=".bcf"), track_contents=True)
		doc.add_product (doc.basename (with_suffix=".bcf"))
		doc.add_source (doc.basename (with_suffix=".bbl"), track_contents=True)


re_bibdata = re.compile(r"\\bibdata{(?P<data>.*)}")
re_citation = re.compile(r"\\citation{(?P<cite>.*)}")
re_undef = re.compile("LaTeX Warning: Citation `(?P<cite>.*)' .*undefined.*")

# The regular expression that identifies errors in BibTeX log files is heavily
# heuristic. The remark is that all error messages end with a text of the form
# "---line xxx of file yyy" or "---while reading file zzz". The actual error
# is either the text before the dashes or the text on the previous line.

re_error = re.compile(
	"---(line (?P<line>[0-9]+) of|while reading) file (?P<file>.*)")

class Bibliography:
	"""
	This class represents a single bibliography for a document.
	"""
	def __init__ (self, document, aux_basename=None):
		"""
		Initialise the bibiliography for the given document. The base name is
		that of the aux file from which citations are taken.
		"""
		self.doc = document
		jobname = os.path.basename (document.target)
		if aux_basename == None:
			aux_basename = jobname
		self.log = jobname + ".log"
		self.aux = aux_basename + ".aux"
		self.bbl = aux_basename + ".bbl"
		self.blg = aux_basename + ".blg"

		cwd = document.vars["cwd"]
		self.bib_path = [cwd, document.vars["path"]]
		self.bst_path = [cwd]

		self.undef_cites = None
		self.used_cites = None
		self.style = None
		self.set_style("plain")
		self.db = {}
		self.sorted = 1
		self.run_needed = 0
		self.crossrefs = None

	#
	# The following method are used to specify the various datafiles that
	# BibTeX uses.
	#

	def do_crossrefs (self, number):
		self.crossrefs = number

	def do_path (self, path):
		self.bib_path.append(self.doc.abspath(path))

	def do_stylepath (self, path):
		self.bst_path.append(self.doc.abspath(path))

	def do_sorted (self, mode):
		self.sorted = mode in ("true", "yes", "1")

	def hook_bibliography (self, loc, bibs):
		for bib in string.split(bibs, ","):
			self.add_db(bib.strip())

	def hook_bibliographystyle (self, loc, style):
		self.set_style(style)

	def add_db (self, name):
		"""
		Register a bibliography database file.
		"""
		for dir in self.bib_path:
			bib = join(dir, name + ".bib")
			if exists(bib):
				self.db[name] = bib
				self.doc.add_source(bib)
				return

	def set_style (self, style):
		"""
		Define the bibliography style used. This method is called when
		\\bibliographystyle is found. If the style file is found in the
		current directory, it is considered a dependency.
		"""
		if self.style:
			old_bst = self.style + ".bst"
			if exists(old_bst) and self.doc.sources.has_key(old_bst):
				self.doc.remove_source(old_bst)

		self.style = style
		for dir in self.bst_path:
			new_bst = join(dir, style + ".bst")
			if exists(new_bst):
				self.bst_file = new_bst
				self.doc.add_source(new_bst)
				return
		self.bst_file = None

	#
	# The following methods are responsible of detecting when running BibTeX
	# is needed and actually running it.
	#

	def pre_compile (self):
		"""
		Run BibTeX if needed before the first compilation. This function also
		checks if BibTeX has been run by someone else, and in this case it
		tells the system that it should recompile the document.
		"""
		if os.path.exists (self.aux):
			self.used_cites, self.prev_dbs = self.parse_aux()
		else:
			self.prev_dbs = None
		if self.doc.log.lines:
			self.undef_cites = self.list_undefs()

		self.run_needed = self.first_run_needed()
		if self.run_needed:
			return self.run()

		if exists (self.bbl):
			if os.path.getmtime (self.bbl) > os.path.getmtime (self.log):
				self.doc.must_compile = 1
		return True

	def first_run_needed (self):
		"""
		The condition is only on the database files' modification dates, but
		it would be more clever to check if the results have changed.
		BibTeXing is also needed when the last run of BibTeX failed, and in
		the very particular case when the style has changed since last
		compilation.
		"""
		if not os.path.exists (self.aux):
			return 0
		if not os.path.exists (self.blg):
			return 1

		dtime = getmtime (self.blg)
		for db in self.db.values():
			if getmtime(db) > dtime:
				msg.log(_("bibliography database %s was modified") % db, pkg="bibtex")
				return 1

		with open (self.blg) as blg:
			for line in blg:
				if re_error.search(line):
					msg.log(_("last BibTeXing failed"), pkg="bibtex")
					return 1

		if self.style_changed():
			return 1
		if self.bst_file and getmtime(self.bst_file) > dtime:
			msg.log(_("the bibliography style file was modified"), pkg="bibtex")
			return 1
		return 0

	def parse_aux (self):
		"""
		Parse the aux files and return the list of all defined citations and
		the list of databases used.
		"""
		last = 0
		cites = {}
		dbs = []
		if self.aux [:-3] == self.log [:-3]: # bib name = job name
			auxnames = self.doc.aux_files
		else:
			auxnames = (self.aux, )
		for auxname in auxnames:
			with open(auxname) as aux:
				for line in aux:
					match = re_citation.match(line)
					if match:
						cite = match.group("cite")
						if not cites.has_key(cite):
							last = last + 1
							cites[cite] = last
						continue
					match = re_bibdata.match(line)
					if match:
						dbs.extend(match.group("data").split(","))
		dbs.sort()

		if self.sorted:
			list = cites.keys()
			list.sort()
			return list, dbs
		else:
			list = [(n,c) for (c,n) in cites.items()]
			list.sort()
			return [c for (n,c) in list], dbs

	def list_undefs (self):
		"""
		Return the list of all undefined citations.
		"""
		cites = {}
		for line in self.doc.log.lines:
			match = re_undef.match(line)
			if match:
				cites[match.group("cite")] = None
		list = cites.keys()
		list.sort()
		return list

	def post_compile (self):
		"""
		This method runs BibTeX if needed to solve undefined citations. If it
		was run, then force a new LaTeX compilation.
		"""
		if not self.bibtex_needed():
			msg.log(_("no BibTeXing needed"), pkg="bibtex")
			return True
		return self.run()

	def run (self):
		"""
		This method actually runs BibTeX with the appropriate environment
		variables set.
		"""
		msg.progress(_("running BibTeX on %s") % self.aux)
		doc = {}
		if len(self.bib_path) != 1:
			doc["BIBINPUTS"] = string.join(self.bib_path +
				[os.getenv("BIBINPUTS", "")], ":")
		if len(self.bst_path) != 1:
			doc["BSTINPUTS"] = string.join(self.bst_path +
				[os.getenv("BSTINPUTS", "")], ":")
		if self.crossrefs is None:
			cmd = ["bibtex"]
		else:
			cmd = ["bibtex", "-min-crossrefs=" + self.crossrefs]
		if self.doc.env.execute (['bibtex', self.aux], doc):
			msg.info(_("There were errors making the bibliography."))
			return False
		self.run_needed = 0
		self.doc.must_compile = 1
		return True

	def bibtex_needed (self):
		"""
		Return true if BibTeX must be run.
		"""
		if self.run_needed:
			return 1
		msg.log (_ ("checking if {} needs BibTeX...").format (self.aux), pkg="bibtex")

		new, dbs = self.parse_aux()

		# If there was a list of used citations, we check if it has
		# changed. If it has, we have to rerun.

		if self.prev_dbs is not None and self.prev_dbs != dbs:
			msg.log(_("the set of databases changed"), pkg="bibtex")
			self.prev_dbs = dbs
			self.used_cites = new
			self.undef_cites = self.list_undefs()
			return 1
		self.prev_dbs = dbs

		# If there was a list of used citations, we check if it has
		# changed. If it has, we have to rerun.

		if self.used_cites:
			if new != self.used_cites:
				msg.log(_("the list of citations changed"), pkg="bibtex")
				self.used_cites = new
				self.undef_cites = self.list_undefs()
				return 1
		self.used_cites = new

		# If there was a list of undefined citations, we check if it has
		# changed. If it has and it is not empty, we have to rerun.

		if self.undef_cites:
			new = self.list_undefs()
			if new == []:
				msg.log(_("no more undefined citations"), pkg="bibtex")
				self.undef_cites = new
			else:
				for cite in new:
					if cite in self.undef_cites:
						continue
					msg.log(_("there are new undefined citations"), pkg="bibtex")
					self.undef_cites = new
					return 1
				msg.log(_("there is no new undefined citation"), pkg="bibtex")
				self.undef_cites = new
				return 0
		else:
			self.undef_cites = self.list_undefs()

		# At this point we don't know if undefined citations changed. If
		# BibTeX has not been run before (i.e. there is no log file) we know
		# that it has to be run now.

		if not exists (self.blg):
			msg.log(_("no BibTeX log file"), pkg="bibtex")
			return 1

		# Here, BibTeX has been run before but we don't know if undefined
		# citations changed.

		if self.undef_cites == []:
			msg.log(_("no undefined citations"), pkg="bibtex")
			return 0

		if getmtime (self.blg) < getmtime (self.log):
			msg.log(_("BibTeX's log is older than the main log"), pkg="bibtex")
			return 1

		return 0

	def clean (self):
		for f in (self.bbl, self.blg):
			try:
				os.remove (f)
				msg.log (_ ("removing {}").format (f), pkg="bibtex")
			except OSError:
				pass

	#
	# The following method extract information from BibTeX log files.
	#

	def style_changed (self):
		"""
		Read the log file if it exists and check if the style used is the one
		specified in the source. This supposes that the style is mentioned on
		a line with the form 'The style file: foo.bst'.
		"""
		if not exists (self.blg):
			return 0
		with open (self.blg) as log:
			for line in log:
				if line.startswith ("The style file: "):
					if line.rstrip()[16:-4] != self.style:
						msg.log(_("the bibliography style was changed"), pkg="bibtex")
						return 1
					else:
						return 0
		msg.warn(_("style file not found in bibtex log"), pkg="bibtex")
		return 0

	def get_errors (self):
		"""
		Read the log file, identify error messages and report them.
		"""
		if not exists (self.blg):
			return
		with open (self.blg) as log:
			last_line = ""
			for line in log:
				m = re_error.search(line)
				if m:
					# TODO: it would be possible to report the offending code.
					if m.start() == 0:
						text = string.strip(last_line)
					else:
						text = string.strip(line[:m.start()])
					line = m.group("line")
					if line: line = int(line)
					d =	{
						"pkg": "bibtex",
						"kind": "error",
						"text": text
						}
					d.update( m.groupdict() )

					# BibTeX does not report the path of the database in its log.

					file = d["file"]
					if file[-4:] == ".bib":
						file = file[:-4]
					if self.db.has_key(file):
						d["file"] = self.db[file]
					elif self.db.has_key(file + ".bib"):
						d["file"] = self.db[file + ".bib"]
					yield d
				last_line = line
