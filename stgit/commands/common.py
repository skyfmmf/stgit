"""Function/variables common to all the commands
"""

__copyright__ = """
Copyright (C) 2005, Catalin Marinas <catalin.marinas@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License version 2 as
published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
"""

import sys, os, os.path, re
from optparse import OptionParser, make_option

from stgit.utils import *
from stgit import stack, git, basedir
from stgit.config import config, file_extensions

crt_series = None


# Command exception class
class CmdException(Exception):
    pass


# Utility functions
class RevParseException(Exception):
    """Revision spec parse error."""
    pass

def parse_rev(rev):
    """Parse a revision specification into its
    patchname@branchname//patch_id parts. If no branch name has a slash
    in it, also accept / instead of //."""
    files, dirs = list_files_and_dirs(os.path.join(basedir.get(),
                                                   'refs', 'heads'))
    if len(dirs) != 0:
        # We have branch names with / in them.
        branch_chars = r'[^@]'
        patch_id_mark = r'//'
    else:
        # No / in branch names.
        branch_chars = r'[^@/]'
        patch_id_mark = r'(/|//)'
    patch_re = r'(?P<patch>[^@/]+)'
    branch_re = r'@(?P<branch>%s+)' % branch_chars
    patch_id_re = r'%s(?P<patch_id>[a-z.]*)' % patch_id_mark

    # Try //patch_id.
    m = re.match(r'^%s$' % patch_id_re, rev)
    if m:
        return None, None, m.group('patch_id')

    # Try path[@branch]//patch_id.
    m = re.match(r'^%s(%s)?%s$' % (patch_re, branch_re, patch_id_re), rev)
    if m:
        return m.group('patch'), m.group('branch'), m.group('patch_id')

    # Try patch[@branch].
    m = re.match(r'^%s(%s)?$' % (patch_re, branch_re), rev)
    if m:
        return m.group('patch'), m.group('branch'), None

    # No, we can't parse that.
    raise RevParseException

def git_id(rev):
    """Return the GIT id
    """
    if not rev:
        return None
    try:
        patch, branch, patch_id = parse_rev(rev)
        if branch == None:
            series = crt_series
        else:
            series = stack.Series(branch)
        if patch == None:
            patch = series.get_current()
            if not patch:
                raise CmdException, 'No patches applied'
        if patch in series.get_applied() or patch in series.get_unapplied():
            if patch_id in ['top', '', None]:
                return series.get_patch(patch).get_top()
            elif patch_id == 'bottom':
                return series.get_patch(patch).get_bottom()
            elif patch_id == 'top.old':
                return series.get_patch(patch).get_old_top()
            elif patch_id == 'bottom.old':
                return series.get_patch(patch).get_old_bottom()
        if patch == 'base' and patch_id == None:
            return read_string(series.get_base_file())
    except RevParseException:
        pass
    return git.rev_parse(rev + '^{commit}')

def check_local_changes():
    if git.local_changes():
        raise CmdException, \
              'local changes in the tree. Use "refresh" to commit them'

def check_head_top_equal():
    if not crt_series.head_top_equal():
        raise CmdException, \
              'HEAD and top are not the same. You probably committed\n' \
              '  changes to the tree outside of StGIT. If you know what you\n' \
              '  are doing, use the "refresh -f" command'

def check_conflicts():
    if os.path.exists(os.path.join(basedir.get(), 'conflicts')):
        raise CmdException, 'Unsolved conflicts. Please resolve them first'

def print_crt_patch(branch = None):
    if not branch:
        patch = crt_series.get_current()
    else:
        patch = stack.Series(branch).get_current()

    if patch:
        print 'Now at patch "%s"' % patch
    else:
        print 'No patches applied'

def resolved(filename, reset = None):
    if reset:
        reset_file = filename + file_extensions()[reset]
        if os.path.isfile(reset_file):
            if os.path.isfile(filename):
                os.remove(filename)
            os.rename(reset_file, filename)

    git.update_cache([filename], force = True)

    for ext in file_extensions().values():
        fn = filename + ext
        if os.path.isfile(fn):
            os.remove(fn)

def resolved_all(reset = None):
    conflicts = git.get_conflicts()
    if conflicts:
        for filename in conflicts:
            resolved(filename, reset)
        os.remove(os.path.join(basedir.get(), 'conflicts'))

def push_patches(patches, check_merged = False):
    """Push multiple patches onto the stack. This function is shared
    between the push and pull commands
    """
    forwarded = crt_series.forward_patches(patches)
    if forwarded > 1:
        print 'Fast-forwarded patches "%s" - "%s"' % (patches[0],
                                                      patches[forwarded - 1])
    elif forwarded == 1:
        print 'Fast-forwarded patch "%s"' % patches[0]

    names = patches[forwarded:]

    # check for patches merged upstream
    if check_merged:
        print 'Checking for patches merged upstream...',
        sys.stdout.flush()

        merged = crt_series.merged_patches(names)

        print 'done (%d found)' % len(merged)
    else:
        merged = []

    for p in names:
        print 'Pushing patch "%s"...' % p,
        sys.stdout.flush()

        if p in merged:
            crt_series.push_patch(p, empty = True)
            print 'done (merged upstream)'
        else:
            modified = crt_series.push_patch(p)

            if crt_series.empty_patch(p):
                print 'done (empty patch)'
            elif modified:
                print 'done (modified)'
            else:
                print 'done'

def pop_patches(patches, keep = False):
    """Pop the patches in the list from the stack. It is assumed that
    the patches are listed in the stack reverse order.
    """
    p = patches[-1]
    if len(patches) == 1:
        print 'Popping patch "%s"...' % p,
    else:
        print 'Popping "%s" - "%s" patches...' % (patches[0], p),
    sys.stdout.flush()

    crt_series.pop_patch(p, keep)

    print 'done'

def parse_patches(patch_args, patch_list):
    """Parse patch_args list for patch names in patch_list and return
    a list. The names can be individual patches and/or in the
    patch1..patch2 format.
    """
    patches = []

    for name in patch_args:
        pair = name.split('..')
        for p in pair:
            if p and not p in patch_list:
                raise CmdException, 'Unknown patch name: %s' % p

        if len(pair) == 1:
            # single patch name
            pl = pair
        elif len(pair) == 2:
            # patch range [p1]..[p2]
            # inclusive boundary
            if pair[0]:
                first = patch_list.index(pair[0])
            else:
                first = 0
            # exclusive boundary
            if pair[1]:
                last = patch_list.index(pair[1]) + 1
            else:
                last = len(patch_list)

            if last > first:
                pl = patch_list[first:last]
            else:
                pl = patch_list[(last - 1):(first + 1)]
                pl.reverse()
        else:
            raise CmdException, 'Malformed patch name: %s' % name

        for p in pl:
            if p in patches:
                raise CmdException, 'Duplicate patch name: %s' % p

        patches += pl

    return patches

def name_email(address):
    """Return a tuple consisting of the name and email parsed from a
    standard 'name <email>' or 'email (name)' string
    """
    address = re.sub('[\\\\"]', '\\\\\g<0>', address)
    str_list = re.findall('^(.*)\s*<(.*)>\s*$', address)
    if not str_list:
        str_list = re.findall('^(.*)\s*\((.*)\)\s*$', address)
        if not str_list:
            raise CmdException, 'Incorrect "name <email>"/"email (name)" string: %s' % address
        return ( str_list[0][1], str_list[0][0] )

    return str_list[0]

def name_email_date(address):
    """Return a tuple consisting of the name, email and date parsed
    from a 'name <email> date' string
    """
    address = re.sub('[\\\\"]', '\\\\\g<0>', address)
    str_list = re.findall('^(.*)\s*<(.*)>\s*(.*)\s*$', address)
    if not str_list:
        raise CmdException, 'Incorrect "name <email> date" string: %s' % address

    return str_list[0]

def make_patch_name(msg):
    """Return a string to be used as a patch name. This is generated
    from the top line of the string passed as argument.
    """
    if not msg:
        return None

    subject_line = msg.lstrip().split('\n', 1)[0].lower()
    return re.sub('[\W]+', '-', subject_line).strip('-')
