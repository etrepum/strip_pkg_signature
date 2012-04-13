#!/usr/bin/env python
# encoding: utf-8
"""
flatpkgfixer.py

"""
#
# NOTE:
# This is a modified version of the original. The modifications
# replace pkgutil usage with strip_pkg_signature.py. The original
# can be found here:
# http://managingosx.wordpress.com/2012/03/24/fixing-packages-with-expired-signatures
#
# Copyright 2012 Greg Neagle.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import os
import optparse
import plistlib
import shutil
import subprocess
import tempfile
from xml.parsers.expat import ExpatError

from strip_pkg_signature import strip_signature, XARFormatError

def getFirstPlist(textString):
    """Gets the next plist from a text string that may contain one or
    more text-style plists.
    Returns a tuple - the first plist (if any) and the remaining
    string after the plist"""
    plist_header = '<?xml version'
    plist_footer = '</plist>'
    plist_start_index = textString.find(plist_header)
    if plist_start_index == -1:
        # not found
        return ("", textString)
    plist_end_index = textString.find(
        plist_footer, plist_start_index + len(plist_header))
    if plist_end_index == -1:
        # not found
        return ("", textString)
    # adjust end value
    plist_end_index = plist_end_index + len(plist_footer)
    return (textString[plist_start_index:plist_end_index],
            textString[plist_end_index:])

# dmg helpers

def DMGhasSLA(dmgpath):
    '''Returns true if dmg has a Software License Agreement.
    These dmgs normally cannot be attached without user intervention'''
    hasSLA = False
    proc = subprocess.Popen(
                ['/usr/bin/hdiutil', 'imageinfo', dmgpath, '-plist'],
                bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (out, err) = proc.communicate()
    if err:
        print >> sys.stderr, (
            'hdiutil error %s with image %s.' % (err, dmgpath))
    if out:
        try:
            plist = plistlib.readPlistFromString(out)
            properties = plist.get('Properties')
            if properties:
                hasSLA = properties.get('Software License Agreement', False)
        except ExpatError:
            pass

    return hasSLA


def mountdmg(dmgpath, use_shadow=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    """
    mountpoints = []
    dmgname = os.path.basename(dmgpath)
    stdin = ''
    if DMGhasSLA(dmgpath):
        stdin = 'Y\n'
    cmd = ['/usr/bin/hdiutil', 'attach', dmgpath,
                '-mountRandom', '/tmp', '-nobrowse', '-plist',
                '-owners', 'on']
    if use_shadow:
        shadowname = dmgname + '.shadow'
        shadowpath = os.path.join(TMPDIR, shadowname)
        cmd.extend(['-shadow', shadowpath])
    else:
        shadowpath = None
    proc = subprocess.Popen(cmd, bufsize=-1,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    (pliststr, err) = proc.communicate(stdin)
    if proc.returncode:
        print >> sys.stderr, 'Error: "%s" while mounting %s.' % (err, dmgname)
    if pliststr:
        plist = plistlib.readPlistFromString(pliststr)
        for entity in plist['system-entities']:
            if 'mount-point' in entity:
                mountpoints.append(entity['mount-point'])

    return mountpoints, shadowpath


def unmountdmg(mountpoint):
    """
    Unmounts the dmg at mountpoint
    """
    proc = subprocess.Popen(['/usr/bin/hdiutil', 'detach', mountpoint],
                                bufsize=-1, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    (unused_output, err) = proc.communicate()
    if proc.returncode:
        print >> sys.stderr, 'Polite unmount failed: %s' % err
        print >> sys.stderr, 'Attempting to force unmount %s' % mountpoint
        # try forcing the unmount
        retcode = subprocess.call(['/usr/bin/hdiutil', 'detach', mountpoint,
                                '-force'])
        if retcode:
            print >> sys.stderr, 'Failed to unmount %s' % mountpoint


def expandAndFlatten(sourcepkg, destination=None):
    '''Uses strip_pkg_signature to remove package signing.'''

    strip_signature(sourcepkg, out_fn=destination)


def cleanupFromFailAndExit(errmsg=''):
    '''Print any error message to stderr,
    clean up install data, and exit'''
    if errmsg:
        print >> sys.stderr, errmsg
    # clean up
    if TMPDIR:
        shutil.rmtree(TMPDIR, ignore_errors=True)
    # exit
    exit(1)


TMPDIR = None

def main():
    global TMPDIR

    usage = ('%prog sourceitem destination')
    p = optparse.OptionParser(usage=usage)
    options, arguments = p.parse_args()

    if len(arguments) > 2:
        print >> sys.stderr, 'Too many arguments!'
        p.print_usage(sys.stderr)
        exit(-1)

    if len(arguments) < 2:
        print >> sys.stderr, 'Too few arguments!'
        p.print_usage(sys.stderr)
        exit(-1)

    source_item = arguments[0]
    dest_item = arguments[1]

    if source_item == dest_item:
        print >> sys.stderr, "Source and destination can't be the same!"
        exit(-1)

    if not os.path.exists(source_item):
        print >> sys.stderr, "%s doesn't exist!" % source_item
        exit(-1)

    TMPDIR = tempfile.mkdtemp()
    if source_item.endswith('.pkg'):
        if not os.path.isfile(source_item):
            cleanupFromFailAndExit('%s is a bundle-style package!')
        try:
            expandAndFlatten(source_item, dest_item)
        except XARFormatError, e:
            cleanupFromFailAndExit(str(e))

    elif source_item.endswith('.dmg'):
        # check to see if we're root
        # need to be root to copy things into the DMG with the right
        # ownership and permissions
        if os.geteuid() != 0:
            print >> sys.stderr, (
                'You must run this as root, or via sudo to fix disk images.')
            exit(-1)

        print 'Mounting %s...' % source_item
        mountpoints, shadowpath = mountdmg(source_item, use_shadow=True)
        if not mountpoints:
            cleanupFromFailAndExit('Nothing mounted from %s' % source_item)
        # search mounted diskimage for all packages.
        # expand and reflatten any flat packages we find.
        mountpoint = mountpoints[0]
        flattened_dir = tempfile.mkdtemp()
        try:
            for dirpath, dirnames, filenames in os.walk(mountpoint):
                for name in filenames:
                    if name.endswith('.pkg'):
                        filepath = os.path.join(dirpath, name)
                        if (os.path.isfile(filepath) and not
                            os.path.islink(filepath)):
                            try:
                                flattened_path = os.path.join(
                                    flattened_dir, name)
                                expandAndFlatten(filepath, flattened_path)
                            except XARFormatError, e:
                                unmountdmg(mountpoint)
                                cleanupFromFailAndExit(str(e))
                            # copy reflattened package back to diskimage
                            # at original path
                            os.unlink(filepath)
                            shutil.copy2(flattened_path, filepath)
                            shutil.rmtree(flattened_path, ignore_errors=True)
        except (OSError, IOError), e:
            unmountdmg(mountpoint)
            cleanupFromFailAndExit(
                'Error %s processing packages in %s' % (e, source_item))

        print 'Unmounting %s...' % source_item
        unmountdmg(mountpoint)

        # convert original diskimage + shadow to new UDZO image
        if os.path.isdir(dest_item):
            dest_item = os.path.join(dest_item, os.path.basename(source_item))
        print 'Creating new disk image at %s...' % os.path.abspath(dest_item)
        cmd = ['/usr/bin/hdiutil', 'convert', '-format', 'UDZO',
               '-o', dest_item, source_item, '-shadow', shadowpath]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError, e:
            cleanupFromFailAndExit(
                'Failed to create %s at: %s' % (dest_item, e))

        print 'Done! Converted DMG is at %s' % dest_item

    else:
        print >> sys.stderr, "Don't know what to do with %s!" % source_item

    # clean up
    shutil.rmtree(TMPDIR, ignore_errors=True)


if __name__ == '__main__':
    main()
