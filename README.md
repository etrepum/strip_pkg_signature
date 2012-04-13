``strip_pkg_signatures`` is a tool that removes the signature from Apple
installer .pkg files. This is only useful to install expired packages. For a
detailed description of this issue, see here:

* http://managingosx.wordpress.com/2012/03/24/fixing-packages-with-expired-signatures/
* http://managingosx.wordpress.com/2012/03/24/package-apocalypse/

Apple installer .pkg files are [XAR files](http://code.google.com/p/xar/)
that have an optional ``<signature>`` element in the TOC XML. For each
specified file, this tool reads the header and TOC. If the TOC does not
have a ``<signature>`` then nothing is done. If it does, then it will
(atomically) replace the file with a new one that has no ``<signature>`` in
the TOC.

    usage: ./strip_pkg_signature.py [-h] [--dry-run] [--keep-old]
                                    XARFILE [XARFILE ...]

    positional arguments:
      XARFILE     the xar files to remove signatures from

    optional arguments:
      -h, --help  show this help message and exit
      --dry-run   do not write new xar files
      --keep-old  keep the originals as XARFILE.old
