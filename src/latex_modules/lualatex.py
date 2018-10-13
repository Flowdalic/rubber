import rubber.module_interface

class Module (rubber.module_interface.Module):

    def __init__ (self, document, opt):
        document.program = 'lualatex'
        document.engine = 'LuaLaTeX'

        if document.env.final != document and document.products[0][-4:] != '.pdf':
            raise rubber.GenericError (_("there is already a post-processor registered"))

        document.set_primary_product_suffix (".pdf")
