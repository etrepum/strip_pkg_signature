#!/usr/bin/env python

import os
import sys
import zlib
import struct
import hashlib
import argparse
from binascii import b2a_hex
from xml.etree import cElementTree as etree
from tempfile import NamedTemporaryFile
from shutil import copyfileobj, copy2


class XARFormatError(ValueError):
    pass


class NoChecksum(object):
    def __init__(self, initial=''):
        pass

    def digest(self):
        return ''


MAGIC = 0x78617221 # xar!
VERSIONS = {0, 1}
CHECKSUM = {0: NoChecksum,
            1: hashlib.sha1,
            2: hashlib.md5}


class Struct(object):
    def __init__(self, fmt, fields):
        self.fmt = fmt
        self.fields = fields
        self.size = struct.calcsize(fmt)

    def fromfile(self, f):
        return self.unpack(f.read(self.size))

    def unpack(self, data):
        return dict(zip(self.fields, struct.unpack(self.fmt, data)))

    def pack(self, dct):
        return struct.pack(self.fmt,
                           *(dct[field] for field in self.fields))


HEADER = Struct('>IHHQQI',
                ('magic', 'size', 'version',
                'toc_length_compressed', 'toc_length_uncompressed',
                'cksum_alg'))


def toc_digest(hdr, ztocdata):
    return CHECKSUM[hdr['cksum_alg']](ztocdata).digest()


def readtoc(f):
    hdr = HEADER.fromfile(f)
    if hdr['magic'] != MAGIC:
        raise XARFormatError('magic %r != %r' %
                             (hdr['magic'], MAGIC))
    if hdr['version'] not in VERSIONS:
        raise XARFormatError('version %r not supported' %
                             (hdr['version'],))
    if hdr['cksum_alg'] not in CHECKSUM:
        raise XARFormatError('cksum_alg %r not supported' %
                             (hdr['cksum_alg'],))
    ztocdata = f.read(hdr['toc_length_compressed'])
    tocdata = zlib.decompress(ztocdata)
    if hdr['toc_length_uncompressed'] != len(tocdata):
        raise XARFormatError('toc_length_uncompressed %r != %r' %
                             (hdr['toc_length_uncompressed'],
                              len(tocdata)))
    digest = toc_digest(hdr, ztocdata)
    if digest:
        orig_digest = f.read(len(digest))
        if digest != orig_digest:
            raise XARFormatError('digest %r != %r' %
                                 (b2a_hex(digest),
                                  b2a_hex(orig_digest)))
    return hdr, tocdata


def strip_signature(fn, out_fn=None, dry_run=False, keep_old=False):
    if out_fn is not None:
        if keep_old:
            raise TypeError('keep_old is not compatible with out_fn')
        if os.path.isdir(out_fn):
            out_fn = os.path.join(out_fn, os.path.basename(fn))
    def do(msg, func, *args, **kw):
        if not dry_run:
            if func is not None:
                func(*args, **kw)
        else:
            msg = msg + ' (dry run)'
        print fn, msg
    in_place = out_fn is None
    with open(fn, 'rb') as f:
        hdr, tocdata = readtoc(f)
        new_tocdata = strip_toc_signature(tocdata)
        if new_tocdata is None:
            if in_place:
                do('SKIPPED, already unsigned',
                   None)
            else:
                do('COPIED, already unsigned',
                   copy2, fn, out_fn)
        else:
            do('REPLACED TOC',
               write_xar,
               fn if in_place else out_fn,
               hdr, new_tocdata, f, keep_old)


def write_xar(fn, hdr, tocdata, heap, keep_old=False):
    ztocdata = zlib.compress(tocdata)
    digest = toc_digest(hdr, ztocdata)
    newhdr = dict(hdr,
                  toc_length_uncompressed=len(tocdata),
                  toc_length_compressed=len(ztocdata))
    outf = NamedTemporaryFile(prefix='.' + os.path.basename(fn),
                              dir=os.path.dirname(fn),
                              delete=False)
    try:
        st_mode = os.stat(fn).st_mode
        if os.fstat(outf.fileno()) != st_mode:
            os.fchmod(outf.fileno(), st_mode)
    except OSError:
        pass
    try:
        outf.writelines([HEADER.pack(newhdr),
                         ztocdata,
                         digest])
        copyfileobj(heap, outf)
        outf.close()
    except:
        outf.close()
        os.unlink(outf.name)
        raise
    if keep_old:
        oldfn = fn + '.old'
        if os.path.exists(oldfn):
            os.unlink(oldfn)
        os.link(fn, oldfn)
    os.rename(outf.name, fn)


def strip_toc_signature(xmlstr):
    et = etree.fromstring(xmlstr)
    toc = et.find('toc')
    if not toc:
        return None
    sig = toc.find('signature')
    if not sig:
        return None
    toc.remove(sig)
    return etree.tostring(et)


def main():
    parser = argparse.ArgumentParser(sys.argv[0])
    parser.add_argument('--dry-run', dest='dry_run', action='store_true',
                        help='do not write new xar files')
    parser.add_argument('--keep-old', dest='keep_old', action='store_true',
                        help='keep the originals as XARFILE.old')
    parser.add_argument('xarfiles', metavar='XARFILE', type=str, nargs='+',
                        help='the xar files to remove signatures from')
    args = parser.parse_args()
    for fn in args.xarfiles:
        strip_signature(fn, dry_run=args.dry_run, keep_old=args.keep_old)

if __name__ == '__main__':
    main()
