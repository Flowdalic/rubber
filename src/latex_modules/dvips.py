# This file is part of Rubber and thus covered by the GPL
# (c) Emmanuel Beffara, 2002--2006
"""
PostScript generation through dvips with Rubber.

This module has specific support for Omega: when the name of the main compiler
is "Omega" (instead of "TeX" for instance), then "odvips" is used instead of
"dvips".
"""

import sys

from rubber import _, msg
from rubber.depend import Node

# FIXME: this class may probably be simplified a lot if inheriting
# from rubber.depend.Shell instead of rubber.depend.Node.

class Dep (Node):
	def __init__ (self, doc, target, source):
		Node.__init__(self, doc.env.depends)
		self.add_product (target)
		self.add_source (source)
		self.env = doc.env
		if doc.vars['engine'] == 'Omega':
			tool = 'odvips'
		else:
			tool = 'dvips'
		self.cmd = [tool, source, '-o', target]
		for opt in doc.vars ['paper'].split ():
			self.cmd.extend (('-t', opt))

	def do_options (self, args):
		self.cmd.extend (args)

	def run (self):
		msg.progress(_("running %s on %s") % (self.cmd [0], self.cmd [1]))
		if self.env.execute (self.cmd, kpse=1):
			msg.error(_("%s failed on %s") % (self.cmd [0], self.cmd [1]))
			return False
		return True

def setup (doc, context):
	dvi = doc.env.final.products[0]
	if dvi[-4:] != '.dvi':
		msg.error(_("I can't use dvips when not producing a DVI"))
		sys.exit(2)
	ps = dvi[:-3] + 'ps'
	global dep
	dep = Dep(doc, ps, dvi)
	doc.env.final = dep

def do_options (*args):
	dep.do_options (args)
