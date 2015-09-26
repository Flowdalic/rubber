# vim: noet:ts=4
# This file is part of Rubber and thus covered by the GPL
# Sebastian Kapfer <sebastian.kapfer@fau.de> 2015.
# based on code by Sebastian Reichel and others.
"""
BibLaTeX support for Rubber
"""

from rubber.util import _, msg
import rubber.util
import rubber.biblio
import sys
import rubber.module_interface

class Module (rubber.module_interface.Module):
	def __init__ (self, document, context):
		doc = document

		options = rubber.util.parse_keyval (context["opt"])
		backend = options.setdefault ("backend", "biber")

		if backend not in ("biber", "bibtex", "bibtex8", "bibtexu"):
			msg.error (_("Garbled biblatex backend: backend=%s (aborting)") % backend)
			sys.exit (1)  # abort rather than guess

		self.dep = BibLaTeXDep (doc, backend)
		doc.hook_macro ("bibliography", "a", self.dep.add_bibliography)

		# overwrite the hook which would load the bibtex module
		doc.hook_macro ("bibliographystyle", "a", self.dep.bibliographystyle)

	def do_path (self, path):
		self.dep.do_path (path)

class BibLaTeXDep (rubber.biblio.BibToolDep):
	def __init__ (self, doc, tool):
		rubber.biblio.BibToolDep.__init__ (self, doc.set)
		self.doc = doc
		self.tool = tool

		for suf in [ ".bbl", ".blg", ".run.xml" ]:
			self.add_product (doc.basename (with_suffix = suf))

		if tool == "biber":
			for macro in ("addbibresource", "addglobalbib", "addsectionbib"):
				doc.hook_macro (macro, "oa", self.add_bib_resource)
			self.source = doc.basename (with_suffix = ".bcf")
			doc.add_product (self.source)
		else:
			self.source = doc.basename (with_suffix = ".aux")
			doc.add_product (doc.basename (with_suffix = "-blx.bib"))

		self.add_source (self.source, track_contents = True)
		doc.add_source (doc.basename (with_suffix = ".bbl"), track_contents = True)

	def build_command (self):
		return [ self.tool, self.source ]

	def add_bib_resource (self, doc, opt, name):
		msg.log (_("bibliography resource discovered: %s" % name), pkg="biblio")
		options = rubber.util.parse_keyval (opt)

		# If the file name looks like it contains a control sequence
		# or a macro argument, forget about this resource.
		if name.find('\\') > 0 or name.find('#') > 0:
			return

		# skip Biber remote resources
		if "location" in options and options["location"] == "remote":
			return

		filename = rubber.util.find_resource (name, suffix = ".bib", paths = self.bib_paths)
		if filename is None:
			msg.error (_ ("cannot find bibliography resource %s") % name, pkg="biblatex")
		else:
			self.add_source (filename)

	def add_bibliography (self, doc, names):
		for bib in names.split (","):
			self.add_bib_resource (doc, None, bib.strip ())

	def bibliographystyle (self, loc, bibs):
		msg.warn (_("\\usepackage{biblatex} incompatible with \\bibliographystyle"), pkg="biblatex")
