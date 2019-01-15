"""
This module contains code for handling dependency graphs.
"""
# vim: noet:ts=4

import logging
msg = logging.getLogger (__name__)
import os.path
import subprocess
import rubber.contents
from rubber.util import _

class MakeError (Exception):
    def __init__ (self, msg, errors):
        super (MakeError, self).__init__ (msg)
        self.msg    = msg
        self.errors = errors

def save_cache (cache_path, final):
    msg.debug (_('Creating or overwriting cache file %s') % cache_path)
    with open (cache_path, 'tw') as f:
        for node in final.all_producers ():
            if node.snapshots is not None:
                f.write (node.primary_product ())
                f.write ('\n')
                for i in range (len (node.sources)):
                    f.write ('  ')
                    f.write (rubber.contents.cs2str (node.snapshots [i]))
                    f.write (' ')
                    f.write (node.sources [i].path ())
                    f.write ('\n')

def load_cache (cache_path):
    msg.debug (_('Reading external cache file %s') % cache_path)
    with open (cache_path) as f:
        line = f.readline ()
        while line:
            product = line [:-1]
            sources = []
            snapshots = []
            while True:
                line = f.readline ()
                if not line.startswith ('  '): # Including end of file.
                    break
                limit = 2 + rubber.contents.cs_str_len
                snapshots.append (rubber.contents.str2cs (line [2:limit]))
                sources.append (line [limit + 1:-1])
            node = rubber.contents.factory (product).producer ()
            if node is None:
                msg.debug (_('%s: no such recipe anymore') % product)
            elif list (s.path () for s in node.sources) != sources:
                msg.debug (_('%s: depends on %s not anymore on %s'), product,
                     " ".join (s.path () for s in node.sources),
                     " ".join (sources))
            elif node.snapshots is not None:
                # FIXME: this should not happen. See cweb-latex test.
                msg.debug (_('%s: rebuilt before cache read'), product)
            else:
                msg.debug (_('%s: using cached checksums'), product)
                node.snapshots = snapshots

class Node (object):
    """
    This is the base class to represent dependency nodes. It provides the base
    functionality of date checking and recursive making, supposing the
    existence of a method `run()' in the object.
    """
    def __init__ (self):
        """
        The node registers itself in the dependency set,
        and if a given depedency is not known in the set, a leaf node is made
        for it.
        """
        self.products = []
        # All prerequisites for this recipe. Elements are instances
        # returned by rubber.contents.factory. A None value for the
        # producer means a leaf node.
        self.sources = []
        # A snapshot of each source as they were used during last
        # successful build, or None if no build has been attempted
        # yet.  The order in the list is the one in self.sources,
        # which does not change during build.
        self.snapshots = None
        # making is the lock guarding against making a node while making it
        self.making = False

    # TODO: once this works and noone outside this files use the
    # dependency set, replace it with a more efficient structure: each
    # node can record once and for all whether it causes a circular
    # dependency or not at creation.
    def all_producers (self):
        def rec (node):
            if not node.making:
                node.making = True
                try:
                    yield node
                    for source in node.sources:
                        child = source.producer ()
                        if child is not None:
                            yield from rec (child)
                finally:
                    self.making = False
        yield from rec (self)

    def add_source (self, name):
        """
        Register a new source for this node. If the source is unknown, a leaf
        node is made for it.
        """
        # Do nothing when the name is already listed.
        # The same source may be inserted many times in the same
        # document (an image containing a logo for example).
        s = rubber.contents.factory (name)
        if s not in self.sources:
            self.sources.append (s)

    def remove_source (self, name):
        """
        Remove a source for this node.
        """
        # Fail if the name is not listed.
        self.sources.remove (rubber.contents.factory (name))

    def add_product (self, name):
        """
        Register a new product for this node.
        """
        f = rubber.contents.factory (name)
        assert f not in self.products
        f.set_producer (self)
        self.products.append (f)

    def primary_product (self):
        return self.products [0].path ()

    def make (self):
        """
        Make the destination file. This recursively makes all dependencies,
        then compiles the target if dependencies were modified. The return
        value is
        - False when nothing had to be done
        - True when something was recompiled (among all dependencies)
        MakeError is raised in case of error.
        """
        # The recurrence is similar to all_producers, except that we
        # try each compilations a few times.

        pp = self.primary_product ()

        if self.making:
            msg.debug (_("%s: cyclic dependency, pruning"), pp)
            return False

        rv = False
        self.making = True
        try:
            for patience in range (5):
                msg.debug (_('%s   made from   %s   attempt %i'),
                           ','.join (s.path () for s in self.products),
                           ','.join (s.path () for s in self.sources),
                           patience)

                # make our sources
                for source in self.sources:
                    if source.producer () is None:
                        msg.debug (_("%s: needs %s, leaf"), pp, source.path ())
                    else:
                        msg.debug (_("%s: needs %s, making %s"), pp,
                            source.path (), source.producer ().primary_product ())
                        rv = source.producer ().make () or rv

                # Once all dependent recipes have been run, check the
                # state of the sources on disk.
                snapshots = tuple (s.snapshot () for s in self.sources)

                missing = ','.join (
                    self.sources [i].path () for i in range (len (snapshots))
                    if snapshots [i] == rubber.contents.NO_SUCH_FILE)
                if missing:
                    if isinstance (self, rubber.converters.latex.LaTeXDep) \
                       and self.snapshots is None \
                       and patience == 0:
                        msg.debug (_("%s: missing %s, but first LaTeX run"), pp, missing)
                    else:
                        msg.debug (_("%s: missing %s, pruning"), pp, missing)
                        return rv

                if self.snapshots is None:
                    msg.debug (_("%s: first attempt or --force, building"), pp)
                else:
                    # There has already been a successful build.
                    changed = ','.join (
                        self.sources [i].path () for i in range (len (snapshots))
                        if self.snapshots [i] != snapshots [i])
                    if not changed:
                        msg.debug (_("%s: sources unchanged since last build"), pp)
                        return rv
                    msg.debug (_("%s: some sources changed: %s"), pp, changed)

                if not self.run ():
                    raise MakeError (_("Recipe for {} failed").format (pp),
                                     self.get_errors ())

                # Build was successful.
                self.snapshots = snapshots
                rv = True

            # Patience exhausted.
            raise MakeError (_("Contents of {} do not settle").format (pp),
                             self.get_errors ())

        finally:
            self.making = False

    def run (self):
        """
        This method is called when a node has to be (re)built. It is supposed
        to rebuild the files of this node, returning true on success and false
        on failure. It must be redefined by derived classes.
        """
        return False

    def get_errors (self):
        """
        Report the errors that caused the failure of the last call to run, as
        an iterable object.
        """
        return []

    def clean (self):
        """
        Remove the products of this recipe.
        Nothing recursive happens with dependencies.

                Each override should start with
                super (class, self).clean ()
        """
        for product in self.products:
            path = product.path ()
            if os.path.exists (path):
                msg.info (_("removing %s"), path)
                os.remove (path)

class Shell (Node):
    """
    This class specializes Node for generating files using shell commands.
    """
    def __init__ (self, command):
        super ().__init__ ()
        self.command = command
        self.stdout = None

    def run (self):
        msg.info(_("running: %s") % ' '.join(self.command))
        process = subprocess.Popen (self.command,
            stdin=subprocess.DEVNULL,
            stdout=self.stdout)
        if process.wait() != 0:
            msg.error(_("execution of %s failed") % self.command[0])
            return False
        return True

class Pipe (Shell):
    """
    This class specializes Node for generating files using the stdout of shell commands.
    The 'product' will receive the stdout of 'command'.
    """
    def __init__ (self, command, product):
        super ().__init__ (command)
        self.add_product (product)

    def run (self):
        with open (self.primary_product (), 'bw') as self.stdout:
            ret = super (Pipe, self).run ()
        return ret
