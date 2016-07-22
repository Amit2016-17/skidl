# -*- coding: utf-8 -*-

# MIT license
#
# Copyright (C) 2016 by XESS Corp.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import print_function
from __future__ import unicode_literals
from __future__ import division
from __future__ import absolute_import
from future import standard_library
standard_library.install_aliases()

import sys
import os
import os.path
import re
import logging
import shlex
from copy import deepcopy
from pprint import pprint
import time
import pdb
from builtins import str
from builtins import zip
from builtins import range
from builtins import object

# from schdl import __version__
__version__ = '0.0.1'

logger = logging.getLogger('schdl')

USING_PYTHON2 = (sys.version_info.major == 2)
USING_PYTHON3 = not USING_PYTHON2

DEBUG_OVERVIEW = logging.DEBUG
DEBUG_DETAILED = logging.DEBUG - 1
DEBUG_OBSESSIVE = logging.DEBUG - 2


class count_calls(object):
    """
    Decorator for counting the number of times a function is called.

    This is used for counting errors and warnings passed to logging functions,
    making it easy to track if and how many errors/warnings were issued.
    """

    def __init__(self, func):
        self.func = func
        self.count = 0

    def __call__(self, *args, **kwargs):
        self.count += 1
        return self.func(*args, **kwargs)

# Set up logging.
logger = logging.getLogger('schdl')
log_level = logging.WARNING
handler = logging.StreamHandler(sys.stderr)
handler.setLevel(log_level)
handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(handler)
logger.setLevel(log_level)
logger.error = count_calls(logger.error)
logger.warning = count_calls(logger.warning)


def to_list(x):
    """
    Return x if it is already a list, or return a list if x is a scalar.
    """
    if isinstance(x, (list, tuple)):
        return x  # Already a list, so just return it.
    return [x]  # Wasn't a list, so make it into one.


def list_or_scalar(lst):
    """
    Return a list if passed a multi-element list, otherwise return a single scalar.

    Args:
        lst: Either a list or a scalar.

    Returns:
        * A list if passed a multi-element list.
        * The list element if passed a single-element list.
        * None if passed an empty list.
        * A scalar if passed a scalar.
    """
    if isinstance(lst, (list, tuple)):
        if len(lst) > 1:
            return lst  # Multi-element list, so return it unchanged.
        if len(lst) == 1:
            return lst[0]  # Single-element list, so return the only element.
        return None  # Empty list, so return None.
    return lst  # Must have been a scalar, so return that.


def get_unique_name(lst, attrib, prefix, initial=None):
    """
    Return a name that doesn't collide with another in a list.

    This subroutine is used to generate unique part references (e.g., "R12")
    or unique net names (e.g., "N$5").

    Args:
        lst: The list of objects containing names.
        attrib: The attribute in each object containing the name.
        prefix: The prefix attached to each name.
        initial: The initial setting of the name (can be None).
    """

    # Get list of everything with a name starting with the prefix 
    # and ending with a string of digits.
    filter_dict = {attrib: re.escape(prefix) + '\d+'}
    sub_list = filter(lst, **filter_dict)

    # If there's nothing in the list like that, then return the name that
    # was passed in, or make a new name and check/adjust it for uniqueness.
    if not sub_list:
        if initial:
            return initial
        else:
            # The initial name was None, so start naming using the prefix
            # with number '1' appended to it.
            return get_unique_name(lst, attrib, prefix, prefix + '1')

    # If there are items in the list with names like the one trying to be
    # assigned but there is no inital name given, then add the next one in
    # the existing sequence.
    elif not initial:
        filter_dict = {attrib: re.escape(prefix) + '\d+'}
        sub_sub_list = filter(sub_list, **filter_dict)
        # If there are already 3 resistors named R1, R2, and R3, then
        # name the next resistor R4 where 4 = len(list)+1.
        trial_name = prefix + str(len(sub_sub_list) + 1)
        return get_unique_name(lst, attrib, prefix, trial_name)

    # There are items in the list like the one trying to be assigned,
    # and an initial name was given. See if the initial name collides
    # with an existing name. If not, just return the initial name.
    # But if it does, append an underscore and a number based on the 
    # number of collisions. (For example, R1 would collide with R1, R1_1,
    # and R1_2 so it's name should be adjusted to R1_3.)
    else:
        filter_dict = {attrib: re.escape(initial) + '(_\d+)?'}
        sub_sub_list = filter(sub_list, **filter_dict)
        if sub_sub_list:
            trial_name = initial + '_' + str(len(sub_sub_list))
            return get_unique_name(lst, attrib, prefix, trial_name)
        else:
            return initial


def filter(lst, **criteria):
    """
    Return a list of objects whose attributes match a set of criteria.

    Return a list of objects extracted from a list whose attributes match a
    set of criteria. The match is done using regular expressions.
    Example: filter(pins, name='io[0-9]+', direction='bidir') will
    return all the bidirectional pins of the component that have pin names
    starting with 'io' followed by a number (e.g., 'IO45').

    If an attribute of the lst object is a list or tuple, each entry in the
    list/tuple will be checked for a match. Only one entry needs to match to
    consider the entire attribute a match. This feature is useful when
    searching for objects that contain a list of aliases, such as Part objects.

    Args:
        lst: The list from which objects will be extracted.
        criteria: Keyword-argument pairs. The keyword specifies the attribute
            name while the argument contains the desired value of the attribute.
            Regardless of what type the argument is, it is always compared as if
            it was a string. The argument can also be a regular expression that
            must match the entire string created from the attribute of the list
            object.

    Returns:
        A list of objects whose attributes match *all* the criteria.
    """

    # Place any matching objects from the list in here.
    extract = []

    for item in lst:
        # String-compare an item's attributes to each of the criteria.
        # Break out of the criteria loop and don't add the item to the extract
        # list if *any* of the item's attributes *does not* match.
        for k, v in criteria.items():

            try:
                attr_val = getattr(item, k)
            except AttributeError:
                # If the attribute doesn't exist, then that's a non-match.
                break

            if not isinstance(attr_val, (list, tuple)):
                # If the attribute value from the item in the list is a scalar,
                # see if the value matches the current criterium. If it doesn't,
                # then break from the criteria loop and don't extract this item.
                if not re.fullmatch(
                        str(v), str(attr_val),
                        flags=re.IGNORECASE):
                    break
            else:
                # If the attribute value from the item is a non-scalar,
                # loop through the list of attribute values. If at least one
                # value matches the current criterium, then break from the
                # criteria loop and don't extract this item.
                for val in attr_val:
                    if re.fullmatch(str(v), str(val), flags=re.IGNORECASE):
                        # One of the list of values matched, so break from this
                        # loop and do not execute the break in the
                        # loop's else clause.
                        break
                else:
                    # If we got here, then none of the values in the attribute
                    # list matched the current criterium. Therefore, break out
                    # of the criteria loop and don't add this list item to
                    # the extract list.
                    break
        else:
            # If we get here, then all the item attributes matched and the
            # for criteria loop didn't break, so add this item to the
            # extract list.
            extract.append(item)

    return extract


def unnest_list(nested_list):
    """
    Return a list of items extracted from a nested list.
    """
    lst = []
    for e in nested_list:
        if isinstance(e, (list, tuple)):
            lst.extend(unnest_list(e))
        else:
            lst.append(e)
    return lst


def expand_indices(slice_max, *indices):
    """
    Expand a list of indices into a list of integers and strings.

    Args:
        slice_max: The maximum possible index (used for slice indices).
        indices: A list of indices made up of numbers, slices, text strings.
            The list can also be nested.

    Returns:
        A linear list of all the indices made up only of numbers and strings.
    """
    ids = []
    for i in unnest_list(indices):
        if isinstance(i, slice):
            ids.extend(range(*i.indices(slice_max)))
        elif isinstance(i, (int, type(''))):
            ids.append(i)
        else:
            logger.error('Unknown type in index: {}'.format(type(i)))
            raise Exception
    return ids

##############################################################################


class SchLib(object):
    """
    A class for storing parts from a schematic component library file.

    Attributes:
        filename: The name of the file from which the parts were read.
        parts: The list of parts (composed of Part objects).
        cache: A dict of filenames and their associated SchLib object
            for fast loading of libraries.
    """
    cache = {}  # Cache of previously read part libraries.

    def __init__(self, filename=None, format='KICAD', **attribs):
        """
        Load the object with parts from a library file.

        Args:
            filename: The name of the library file.
            tool: The format of the library file (e.g., 'kicad').
        """

        self.filename = filename
        self.parts = []

        # Load this SchLib with an existing SchLib object if the file name
        # matches one in the cache.
        if filename in self.cache:
            self.__dict__.update(self.cache[filename].__dict__)

        # Otherwise, load from a schematic library file.
        elif format == 'KICAD':
            self.load_kicad_sch_lib(filename)
            self.cache[filename] = self  # Cache a reference to the library.

        # OK, that didn't work so well...
        else:
            logger.error('Unsupported library file format: {}'.format(format))

        # Attach additional attributes to the library.
        for k, v in attribs.items():
            setattr(self, k, v)

    def __len__(self):
        """
        Return number of parts in library.
        """
        return len(self.parts)

    def load_kicad_sch_lib(self, filename=None):
        """
        Load the object with parts from a KiCad schematic library file.

        Args:
            filename: The name of the KiCad schematic library file.
        """
        self.filename = filename
        self.parts = []

        # Try to open the file.
        try:
            f = open(filename)
        except (FileNotFoundError, TypeError):
            logger.error("Can't open file: {}\n".format(filename))
            return

        # Check the file header to make sure it's a KiCad library.
        header = []
        header = [f.readline()]
        if header and 'EESchema-LIBRARY' not in header[0]:
            logger.error(
                'The file {} is not a KiCad Schematic Library File\n'.format(
                    filename))
            return

        # Read the definition of each part line-by-line and then create
        # a Part object that gets stored in the part list.
        part_defn = []
        for line in f.readlines():

            # Skip over comments.
            if line.startswith('#'):
                pass

            # Look for the start of a part definition.
            elif line.startswith('DEF'):
                # Initialize the part definition with the first line.
                # This will also signal that succeeding lines should be added.
                part_defn = [line]

            # If gathering the part definition has begun, then continue adding lines.
            elif part_defn:
                part_defn.append(line)

                # If the current line ends this part definition, then create
                # the Part object and add it to the part list. Be sure to
                # indicate that the Part object is being added to a library
                # and not to a schematic netlist.
                if line.startswith('ENDDEF'):
                    self.parts.append(Part(part_defn=part_defn,
                                           format='KICAD',
                                           destination='LIBRARY'))

                    # Clear the part definition in preparation for the next one.
                    part_defn = []

    def get_parts(self, **criteria):
        """
        Return parts from a library that match *all* the given criteria.

        Args:
            criteria: One or more keyword-argument pairs. The keyword specifies
                the attribute name while the argument contains the desired value
                of the attribute.

        Returns:
            * Return a list of Part objects that match the criteria.
            * Return a Part object if only a single match is found.
        """
        return list_or_scalar(filter(self.parts, **criteria))

    def get_part_by_name(self, name, allow_multiples=False):
        """Return a Part with the given name or alias from the part list."""

        # First check to see if there is a part or parts with a matching name.
        parts = self.get_parts(name=name)

        if not parts:
            # No part with that name, so check for an alias that matches.
            parts = self.get_parts(aliases=name)
            if not parts:
                logger.error('Unable to find part {} in library {}.'.format(
                    name, self.filename))
                raise Exception

        if isinstance(parts, (list, tuple)):
            if allow_multiples:
                parts = [p.parse() for p in parts]
            else:
                logger.warning(
                    'Found multiple parts matching {}. Selecting {}.'.format(
                        name, parts[0].name))
                parts = parts[0]
                parts.parse()
        else:
            parts.parse()

        return parts

    __getitem__ = get_part_by_name

##############################################################################


class Pin(object):
    """
    A class for storing data about pins for a part.

    Attributes:
        net: The electrical net this pin is connected to.
        part: Link to the Part object this pin belongs to.
    """

    NO_DRIVE, ONESIDE_DRIVE, PUSHPULL_DRIVE, POWER_DRIVE = range(4)

    INPUT, OUTPUT, BIDIR, TRISTATE, PASSIVE, UNSPEC, PWRIN, PWROUT, OPENCOLL, OPENEMIT, NOCONNECT = range(
        11)

    pin_info = {
        INPUT: {'function': 'INPUT',
                'drive': NO_DRIVE,
                'receive': ONESIDE_DRIVE, },
        OUTPUT: {'function': 'OUTPUT',
                 'drive': PUSHPULL_DRIVE,
                 'receive': NO_DRIVE, },
        BIDIR: {'function': 'BIDIRECTIONAL',
                'drive': PUSHPULL_DRIVE,
                'receive': NO_DRIVE, },
        TRISTATE: {'function': 'TRISTATE',
                   'drive': PUSHPULL_DRIVE,
                   'receive': NO_DRIVE, },
        PASSIVE: {'function': 'PASSIVE',
                  'drive': NO_DRIVE,
                  'receive': NO_DRIVE, },
        UNSPEC: {'function': 'UNSPECIFIED',
                 'drive': NO_DRIVE,
                 'receive': NO_DRIVE, },
        PWRIN: {'function': 'POWER-IN',
                'drive': NO_DRIVE,
                'receive': POWER_DRIVE, },
        PWROUT: {'function': 'POWER-OUT',
                 'drive': POWER_DRIVE,
                 'receive': NO_DRIVE, },
        OPENCOLL: {'function': 'OPEN-COLLECTOR',
                   'drive': ONESIDE_DRIVE,
                   'receive': NO_DRIVE, },
        OPENEMIT: {'function': 'OPEN-EMITTER',
                   'drive': ONESIDE_DRIVE,
                   'receive': NO_DRIVE, },
        NOCONNECT: {'function': 'NO-CONNECT',
                    'drive': NO_DRIVE,
                    'receive': NO_DRIVE, },
    }

    def __init__(self, **attribs):
        """Initialize the pin."""
        self.net = None
        self.part = None

        # Attach additional attributes to the pin.
        for k, v in attribs.items():
            setattr(self, k, v)

    def __iadd__(self, net):
        """
        Connect a net to a pin.

        Args:
            net: A Net object to be connected to this pin.

        Returns:
            The updated Pin object with the new net connection.

        Raises:
            An exception if trying to attach a net to a pin that is already
            connected to a different net.
        """

        # First, check that the pin is not already connected to a different net.
        # (A pin cannot be connected to more than one net.)
        if self.net and self.net != net:
            logger.error(
                "Can't assign net {} to pin {}-{} of part {}-{} because it's already connected to net {}!".format(
                    net.name, self.num, self.name, self.part.ref,
                    self.part.name, self.net.name))
            return self

        # Assign the net to this pin.
        self.net = net

        # Now, add the pin to the list of pins maintained by the Net object.
        # This ties them together so that a given pin can find the net it
        # connects to, and a given net can find all the pins it's connected to.
        net += self

        return self

    def get_nets(self):
        if self.net is None:
            return []
        return to_list(self.net)

    def get_pins(self):
        return to_list(self)

    def erc_pin_desc(self):
        pin_function = Pin.pin_info[self.func]['function']
        desc = "{f} pin {p.num}/{p.name} of {p.part.name}/{p.part.ref}".format(
            f=pin_function, p=self)
        return desc

##############################################################################


class Part(object):
    """
    A class for storing a definition of a schematic part.

    Attributes:
        ref: String storing the reference of a part within a schematic (e.g., 'R5').
        value: String storing the part value (e.g., '3K3').
        footprint: String storing the PCB footprint associated with a part (e.g., SOIC-8).
        pins: List of Pin objects for this part.
    """

    def __init__(self,
                 lib=None,
                 name=None,
                 part_defn=None,
                 format='KICAD',
                 destination='NETLIST',
                 connections=None,
                 **attribs):
        """
        Create a Part object from a library or a part definition.

        Args:
            lib: Either a SchLib object or a schematic part library file name.
            name: A string with name of the part to find in the library, or to assign to
                the part defined by the part definition.
            part_defn: A list of strings that define the part (usually read from a
                schematic library file).
            format: The format for the library file or part definition (e.g., 'KICAD').
            destination: String that indicates where the part is destined for:
                'NETLIST': The part will become part of a circuit netlist.
                'LIBRARY': The part will be placed in the part list for a library.
            connections: A dictionary with part pin names/numbers as keys and the
                names of nets to which they will be connected as values. For example:
                { 'IN-':'a_in', 'IN+':'GND', '1':'AMPED_OUTPUT', '14':'VCC', '7':'GND' }
            **attribs: Name/value pairs for setting attributes for the part.
                For example, manf_num='LM4808MP-8' would create an attribute
                named 'manf_num' for the part and assign it the value 'LM4808MP-8'.

        Raises:
            * Exception if the part library and definition are both missing.
            * Exception if an unknown file format is requested.
        """

        # Create a Part from a library entry.
        if lib:
            # If the lib argument is a string, then create a library using the
            # string as the library file name.
            if isinstance(lib, type('')):
                lib = SchLib(filename=lib, format=format)

            # Make a copy of the part from the library but don't add it to the netlist.
            part = lib.get_part_by_name(name).copy(1, 'DONT_ADD_TO_NETLIST')

            # Overwrite self with the new part.
            self.__dict__.update(part.__dict__)

            # Make sure all the pins have a valid reference to this part.
            self.associate_part_with_pins()

        # Otherwise, create a Part from a part definition. If the part is
        # destined for a library, then just get its name. If it's going into
        # a netlist, then parse the entire part definition.
        elif part_defn:
            self.format = format
            self.part_defn = part_defn
            self.parse(just_get_name=destination != 'NETLIST')

        else:
            logger.error(
                "Can't make a part without a library & part name or a part definition.")
            raise Exception

        # Add additional attributes to the part.
        for k, v in attribs.items():
            setattr(self, k, v)

        # If the part is going to be an element in a circuit, then add it to the
        # the circuit and make any indicated pin/net connections.
        if destination == 'NETLIST':
            SubCircuit.add_part(self)
            if isinstance(connections, dict):
                for pin, net in connections.items():
                    net += self[pin]

    def parse(self, just_get_name=False):
        """
        Create a part using a part definition.

        Args:
            part_defn: A list of strings that define the part (usually read
                from a schematic library file).
            format: Part definition format, e.g. 'KICAD'.
            just_get_name: When true, just get the name and aliases for the
                part. Leave the rest unparsed.
        """
        if self.format == 'KICAD':
            self.parse_kicad(just_get_name)
        else:
            logger.error(
                "Can't create a part with an unknown file format: {}.".format(
                    format))
            raise Exception

    def parse_kicad(self, just_get_name=False):
        """
        Create a Part using a part definition from a KiCad schematic library.

        This method was written based on the code from
        https://github.com/KiCad/kicad-library-utils/tree/master/schlib.
        It's covered by GPL3.

        Args:
            part_defn: A list of strings that define the part (usually read from a
                schematic library file). Can also be None.
            just_get_name: If true, scan the part definition until the
                name and aliases are found. The rest of the definition
                will be parsed if the part is actually used.
        """

        _DEF_KEYS = ['name', 'reference', 'unused', 'text_offset',
                     'draw_pinnumber', 'draw_pinname', 'unit_count',
                     'units_locked', 'option_flag']
        _F0_KEYS = ['reference', 'posx', 'posy', 'text_size', 'text_orient',
                    'visibility', 'htext_justify', 'vtext_justify']
        _FN_KEYS = ['name', 'posx', 'posy', 'text_size', 'text_orient',
                    'visibility', 'htext_justify', 'vtext_justify',
                    'fieldname']
        _ARC_KEYS = ['posx', 'posy', 'radius', 'start_angle', 'end_angle',
                     'unit', 'convert', 'thickness', 'fill', 'startx',
                     'starty', 'endx', 'endy']
        _CIRCLE_KEYS = ['posx', 'posy', 'radius', 'unit', 'convert',
                        'thickness', 'fill']
        _POLY_KEYS = ['point_count', 'unit', 'convert', 'thickness', 'points',
                      'fill']
        _RECT_KEYS = ['startx', 'starty', 'endx', 'endy', 'unit', 'convert',
                      'thickness', 'fill']
        _TEXT_KEYS = ['direction', 'posx', 'posy', 'text_size', 'text_type',
                      'unit', 'convert', 'text', 'italic', 'bold', 'hjustify',
                      'vjustify']
        _PIN_KEYS = ['name', 'num', 'posx', 'posy', 'length', 'direction',
                     'name_text_size', 'num_text_size', 'unit', 'convert',
                     'electrical_type', 'pin_type']
        _DRAW_KEYS = {'arcs': _ARC_KEYS,
                      'circles': _CIRCLE_KEYS,
                      'polylines': _POLY_KEYS,
                      'rectangles': _RECT_KEYS,
                      'texts': _TEXT_KEYS,
                      'pins': _PIN_KEYS}
        _DRAW_ELEMS = {'arcs': 'A',
                       'circles': 'C',
                       'polylines': 'P',
                       'rectangles': 'S',
                       'texts': 'T',
                       'pins': 'X'}
        _KEYS = {'DEF': _DEF_KEYS,
                 'F0': _F0_KEYS,
                 'F': _FN_KEYS,
                 'A': _ARC_KEYS,
                 'C': _CIRCLE_KEYS,
                 'P': _POLY_KEYS,
                 'S': _RECT_KEYS,
                 'T': _TEXT_KEYS,
                 'X': _PIN_KEYS}

        # Return if there's nothing to do (i.e., part has already been parsed).
        if not self.part_defn:
            return

        self.fplist = []  # Footprint list.
        self.aliases = []  # Part aliases.
        building_fplist = False  # True when working on footprint list in defn.
        building_draw = False  # True when gathering part drawing from defn.

        # Go through the part definition line-by-line.
        for line in self.part_defn:

            # Split the line into words.
            line = line.replace('\n', '')
            s = shlex.shlex(line)
            s.whitespace_split = True
            s.commenters = ''
            s.quotes = '"'
            line = list(s)  # Place the words in a list.

            # The first word indicates the type of part definition data that will follow.
            if line[0] in _KEYS:
                # Get the keywords for the current part definition data.
                key_list = _KEYS[line[0]]
                # Make a list of the values in the part data associated with each key.
                # Use an empty string for any missing values so every key will be
                # associated with something.
                values = line[1:] + [
                    '' for n in range(len(key_list) - len(line[1:]))
                ]

            # Create a dictionary of part definition keywords and values.
            if line[0] == 'DEF':
                self.definition = dict(list(zip(_DEF_KEYS, values)))
                self.name = self.definition['name']

                # To handle libraries quickly, just get the name and
                # aliases and only parse the rest of the part definition later.
                if just_get_name:
                    if self.aliases:
                        # Name found, aliases already found so we're done.
                        return
                    # Name found so scan defn to see if aliases are present.
                    # (The majority of parts don't have aliases.)
                    for line in self.part_defn:
                        if re.match('^\s*ALIAS\s', line):
                            # Break and keep parsing defn if aliases are present.
                            break
                    else:
                        # No aliases found, so part name is all that's needed.
                        return

            # Create a dictionary of F0 part field keywords and values.
            elif line[0] == 'F0':
                self.fields = []
                self.fields.append(dict(list(zip(_F0_KEYS, values))))

            # Create a dictionary of the other part field keywords and values.
            elif line[0][0] == 'F':
                # Make a list of field values with empty strings for missing fields.
                values = line[1:] + [
                    '' for n in range(len(_FN_KEYS) - len(line[1:]))
                ]
                self.fields.append(dict(list(zip(_FN_KEYS, values))))

            # Create a list of part aliases.
            elif line[0] == 'ALIAS':
                self.aliases = [alias for alias in line[1:]]
                if just_get_name and self.name:
                    # Aliases found, name already found so we're done.
                    return

            # Start the list of part footprints.
            elif line[0] == '$FPLIST':
                building_fplist = True
                self.fplist = []

            # End the list of part footprints.
            elif line[0] == '$ENDFPLIST':
                building_fplist = False

            # Start gathering the drawing primitives for the part symbol.
            elif line[0] == 'DRAW':
                building_draw = True
                self.draw = {
                    'arcs': [],
                    'circles': [],
                    'polylines': [],
                    'rectangles': [],
                    'texts': [],
                    'pins': []
                }

            # End the gathering of drawing primitives.
            elif line[0] == 'ENDDRAW':
                building_draw = False

            # Every other line is either a footprint or a drawing primitive.
            else:
                # If the footprint list is being built, then add this line to it.
                if building_fplist:
                    self.fplist.append(line[0])

                # Else if the drawing primitives are being gathered, process the
                # current line to see what type of primitive is in play.
                elif building_draw:

                    # Gather arcs.
                    if line[0] == 'A':
                        self.draw['arcs'].append(dict(list(zip(_ARC_KEYS,
                                                               values))))

                    # Gather circles.
                    if line[0] == 'C':
                        self.draw['circles'].append(dict(list(zip(_CIRCLE_KEYS,
                                                                  values))))

                    # Gather polygons.
                    if line[0] == 'P':
                        n_points = int(line[1])
                        points = line[5:5 + (2 * n_points)]
                        values = line[1:5] + [points]
                        if len(line) > (5 + len(points)):
                            values += [line[-1]]
                        else:
                            values += ['']
                        self.draw['polylines'].append(dict(list(zip(_POLY_KEYS,
                                                                    values))))

                    # Gather rectangles.
                    if line[0] == 'S':
                        self.draw['rectangles'].append(dict(list(zip(
                            _RECT_KEYS, values))))

                    # Gather text.
                    if line[0] == 'T':
                        self.draw['texts'].append(dict(list(zip(_TEXT_KEYS,
                                                                values))))

                    # Gather the pin symbols. This is what we really want since
                    # this defines the names, numbers and attributes of the
                    # pins associated with the part.
                    if line[0] == 'X':
                        self.draw['pins'].append(dict(list(zip(_PIN_KEYS,
                                                               values))))

        # Define some shortcuts to part information.
        self.num_units = int(
            self.definition['unit_count'])  # # of units within the part.
        self.name = self.definition['name']  # Part name (e.g., 'LM324').
        self.ref_prefix = self.definition[
            'reference']  # Part ref prefix (e.g., 'R').

        # Clear the part reference field directly. Don't use the setter function
        # since it will try to generate and assign a unique part reference if
        # passed a value of None.
        self._ref = None

        # Make a Pin object from the information in the KiCad pin data fields.
        def kicad_pin_to_pin(kicad_pin):
            p = Pin()
            # Replicate the KiCad pin fields as attributes in the Pin object.
            # Note that this update will not give the pins valid references
            # to the current part, but we'll fix that soon.
            p.__dict__.update(kicad_pin)

            pin_type_translation = {'I': Pin.INPUT,
                                    'O': Pin.OUTPUT,
                                    'B': Pin.BIDIR,
                                    'T': Pin.TRISTATE,
                                    'P': Pin.PASSIVE,
                                    'U': Pin.UNSPEC,
                                    'W': Pin.PWRIN,
                                    'w': Pin.PWROUT,
                                    'C': Pin.OPENCOLL,
                                    'E': Pin.OPENEMIT,
                                    'N': Pin.NOCONNECT}
            p.func = pin_type_translation[p.electrical_type]

            return p

        self.pins = [kicad_pin_to_pin(p) for p in self.draw['pins']]

        # Make sure all the pins have a valid reference to this part.
        self.associate_part_with_pins()

        # Part definition has been parsed, so clear it out. This prevents a
        # part from being parsed more than once.
        self.part_defn = None

    def associate_part_with_pins(self):
        """
        Make sure all the pins in a part have valid references to the part.
        """
        for p in self.pins:
            p.part = self

    def copy(self, num_copies=1, destination='NETLIST', **attribs):
        """
        Make zero or more copies of this part while maintaining all pin/net
        connections.

        Args:
            num_copies: Number of copies to make of this part.

        Returns:
            A list of Part copies or a single Part if num_copies==1.
            destination: String that indicates where the part is destined for:
                'NETLIST': The part will become part of a circuit netlist.
                'LIBRARY': The part will be placed in the part list for a library.

        Raises:
            Exception if the requested number of copies is a non-integer or negative.
        """

        # Check that a valid number of copies is requested.
        if not isinstance(num_copies, int):
            logger.error(
                "Can't make a non-integer number ({}) of copies of a part!".format(
                    num_copies))
            raise Exception
        if num_copies < 0:
            logger.error(
                "Can't make a negative number ({}) of copies of a part!".format(
                    num_copies))
            raise Exception

        # Now make copies of the part one-by-one.
        copies = []
        for i in range(num_copies):
            cpy = deepcopy(self)

            # Clear the part reference of the copied part so a unique reference
            # can be assigned when the part is added to the circuit.
            # (This is not strictly necessary since the part reference will be
            # adjusted to be unique if needed during the addition process.)
            cpy._ref = None

            # copy the pin/net connections of the original to the part copy.
            for i, pin in enumerate(cpy.pins):

                # Tell the copied pins they belong to the copied part.
                pin.part = cpy

                # Disconnect the pins of the copied part and then reconnect
                # them to the same nets. This is done to update the nets
                # with the new pin connections to the copied part.
                original_net = pin.net  # Remember net this pin was connected to.

                pin.net = None  # Disconnect pin of copied part from net.

                # Now connect the copied pin back to the net.
                if original_net:
                    original_net += pin

            for k, v in attribs.items():
                setattr(cpy, k, v)

            # Add the part copy to the list of copies and then add the
            # part to the circuit netlist (if requested).
            copies.append(cpy)
            if destination == 'NETLIST':
                SubCircuit.add_part(cpy)

        return list_or_scalar(copies)

    """Make copies with the multiplication operator"""
    __mul__ = copy
    __rmul__ = copy

    def get_pins(self, *pin_ids):
        """
        Return list of part pins selected by pin numbers or names.

        For example, this would return a last of part pins that match
        any of these::

            lm324.get_pins(1, 'VCC', 'IN.*', 4:8, range(4,8))

        Args:
            pin_ids: A list of strings containing pin names, numbers,
                regular expressions, slices, lists or tuples.

        Returns:
            A list of pins matching the given IDs, or just a single Pin object
            if only a single match was found. Or None if no match was found.
        """

        pin_ids = expand_indices(len(self.pins), *pin_ids)

        # Go through the list of pin IDs one-by-one.
        pins = []
        for p_id in pin_ids:

            # Pin ID is an integer.
            if isinstance(p_id, int):
                pins.extend(to_list(self.filter_pins(num=str(p_id))))

            # Pin ID is a string containing a number or name.
            else:
                # First try to get pins using the string as a number.
                tmp_pins = self.filter_pins(num=p_id)
                if tmp_pins:
                    pins.extend(to_list(tmp_pins))
                # If that didn't work, try using the string as a pin name.
                else:
                    pins.extend(to_list(self.filter_pins(name=p_id)))

        return list_or_scalar(pins)

    """Return list of part pins selected by pin numbers/names using index brackets."""
    __getitem__ = get_pins

    def filter_pins(self, **criteria):
        """
        Return a list of part pins whose attributes match a list of criteria.

        Return a list of pins extracted from a part whose attributes match a
        list of criteria. The match is done using regular expressions.
        Example: filter_pins(name='io[0-9]+', direction='bidir') will
        return all the bidirectional pins of the component that have pin names
        starting with 'io' followed by a number (e.g., 'IO45').

        Args:
            criteria: Keyword-argument pairs. The keyword specifies the attribute
                name while the argument contains the desired value of the attribute.

        Returns:
            A list of Pins whose attributes match *all* the criteria.
        """
        return filter(self.pins, **criteria)

    def connect(self, pin_ids, nets):
        """
        Connect nets or pins of other parts to the specified pins of this part.

        For example, this would connect a net to a part pin::

            lm324.connect('IN-', input_net)

        Args:
            pin_ids: List of IDs of pins for this part. See get_pins() for the
                types of acceptable pin IDs.
            nets: Net objects.

        Raises:
            Exception if the list of pins to connect to is empty.
        """

        pins = self.get_pins(pin_ids)  # Get the pins selected by the pin IDs.
        pins = to_list(pins)  # Make list in case only a single pin was found.

        if pins is None or len(pins) == 0:
            logger.error("No pins to attach to!")
            raise Exception

        nets = unnest_list(to_list(nets))  # Make sure nets is a list.
        expanded_nets = []
        for n in nets:
            if isinstance(n, Pin):
                if not n.get_nets():
                    n += Net()
            expanded_nets.extend(n.get_nets())

        # If just a single net is to be connected, make a list out of it that's
        # just as long as the list of pins to connect to. This will connect
        # multiple pins to the same net.
        if len(expanded_nets) == 1:
            expanded_nets = [expanded_nets[0] for _ in range(len(pins))]

        # Now connect the pins to the nets.
        if len(expanded_nets) == len(pins):
            for pin, net in zip(pins, expanded_nets):
                net += pin
        else:
            logger.error(
                "Can't attach differing numbers of pins ({}) and nets ({})!".format(
                    len(pins), len(expanded_nets)))
            raise Exception

    __setitem__ = connect

    @property
    def ref(self):
        """Return the part reference."""
        return self._ref

    @ref.setter
    def ref(self, r):
        """
        Set the part reference.

        This sets the part reference to be a unique identifier.

        Args:
            r: The requested reference for the part. If another part with the
                same reference is found, this reference is modified by adding
                an underscore and a counter value based on the number of duplicates.
                If r is None, then r is assigned a unique reference consisting
                of the reference prefix for the part followed by a number.
        """
        self._ref = get_unique_name(SubCircuit.circuit_parts, 'ref',
                                    self.ref_prefix, r)
        return

    @ref.deleter
    def ref(self):
        """Delete the part reference."""
        self._ref = None

    @property
    def value(self):
        """Return the part value."""
        return self._value

    @value.setter
    def value(self, value):
        """Set the part value."""
        self._value = str(value)

    @value.deleter
    def value(self):
        """Delete the part value."""
        del self._value

    @property
    def foot(self):
        """Return the part footprint."""
        return self._foot

    @foot.setter
    def foot(self, footprint):
        """Set the part footprint."""
        self._foot = str(footprint)

    @foot.deleter
    def foot(self):
        """Delete the part footprint."""
        del self._foot

    def unit(self, *unit_ids):
        """
        Return a unit of this part.

        Many parts are organized into smaller pieces called units. This method
        will search a Part for one or more unit identifiers and return a single
        PartUnit object containing the pins from the matching units.
        For example, this will return unit 1 from a part::

            lm324.unit(1)

        And this will return a single PartUnit that combines two units of a part::

            lm324.unit(2, 4)

        You can even use slices:

            lm324.unit(2:5)

        Args:
            unit_ids: One or more unit identifiers to search for.

        Returns:
            A PartUnit object.
        """
        return PartUnit(self, *unit_ids)

    def is_connected(self):
        """
        Return T/F depending upon whether a part is connected in a netlist.

        If a part has pins but none of them are connected to nets, then
        this method will return False. Otherwise, it will return True even if
        the part has no pins (which can be the case for mechanical parts,
        silkscreen logos, or other non-electrical schematic elements).
        """

        # Assume parts without pins (like mech. holes) are always connected.
        if len(self.pins) == 0:
            return True

        # If any pin is found to be connected to a net, return True
        for p in self.pins:
            if p.net is not None:
                return True

        # No net connections found, so return False.
        return False

    def erc(self):
        """
        Do electrical rules check on a part in the schematic.
        """
        for p in self.pins:
            if p.net is None and p.func != Pin.NOCONNECT:
                erc_logger.warning('Unconnected pin: Pin {p}.'.format(
                    p=p.erc_pin_desc()))
            if p.net is not None and p.func == Pin.NOCONNECT:
                erc_logger.warning(
                    'Incorrectly connected pin: Pin {p} should not be connected to a net (n).'.format(
                        p=p.erc_pin_desc(), n=p.net.name))

    def generate_netlist_component(self, format='KICAD'):
        """
        Generate the part information for inclusion in a netlist.

        Args:
            format: The format for the netlist file (e.g., 'KICAD').
        """

        def gen_netlist_comp_kicad():
            ref = self.ref
            try:
                value = self.value
                if not value:
                    value = self.name
            except AttributeError:
                try:
                    value = self.name
                except AttributeError:
                    value = self.ref_prefix
            try:
                footprint = self.footprint
            except AttributeError:
                logger.warning('No footprint for {part}/{ref}.'.format(
                    part=self.name, ref=ref))
                footprint = 'No Footprint'

            txt = '    (comp (ref {ref})\n      (value {value})\n      (footprint {footprint}))'.format(
                ref=ref, value=value, footprint=footprint)
            return txt

        if format == 'KICAD':
            return gen_netlist_comp_kicad()
        else:
            logger.error(
                "Can't generate netlist in an unknown format ({}).".format(
                    format))
            raise Exception
            return ''

##############################################################################


class PartUnit(Part):
    """
    Many parts are organized into smaller pieces called units. This object
    acts like a Part but contains only a subset of the pins of a part.
    """

    def __init__(self, part, *unit_ids):
        """
        Create a PartUnit from the pins of one or more units in a Part object.

        Create a PartUnit from one or more units and return a single
        PartUnit object containing the pins from the matching units.
        For example, this will return unit 1 from a part::

            PartUnit(lm324, 1)

        And this will return a single PartUnit that combines two units of a part::

            PartUnit(lm324, 2, 4)

        You can even use slices:

            PartUnit(lm324, 2:5)
        """

        # Give the PartUnit the same information as the Part it is generated
        # from so it can act the same way, just with fewer pins.
        for k, v in part.__dict__.items():
            self.__dict__[k] = v

        # Collect pins into a set so there won't be any duplicates.
        unique_pins = set()

        # Now collect the pins the unit will have access to.
        for unit_id in expand_indices(part.num_units, unit_ids):
            unique_pins |= set(part.filter_pins(unit=unit_id))

        # Store the pins in the PartUnit.
        self.pins = unique_pins[:]

##############################################################################


class Net(object):
    def __init__(self, name=None, *pins, **attribs):
        self.name = name
        self._drive = Pin.NO_DRIVE
        self.pins = []

        # Attach whatever pins were given.
        self.add_pins(*pins)

        # Attach additional attributes to the net.
        for k, v in attribs.items():
            setattr(self, k, v)

    def __len__(self):
        return len(self.pins)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self._name = get_unique_name(SubCircuit.circuit_nets, 'name', 'N$',
                                     name)

    @name.deleter
    def name(self):
        del self._name

    @property
    def drive(self):
        return self._drive

    @drive.setter
    def drive(self, drive):
        self._drive = max(drive, self._drive)

    @drive.deleter
    def drive(self):
        del self._drive

    def get_pins(self):
        return to_list(self.pins)

    def get_nets(self):
        return to_list(self)

    def copy(self, num_copies=1):
        """
        Make zero or more copies of this net.

        Args:
            num_copies: Number of copies to make of this part.

        Raises:
            Exception if the requested number of copies is a non-integer or negative.
        """

        # Check that a valid number of copies is requested.
        if not isinstance(num_copies, int):
            logger.error(
                "Can't make a non-integer number ({}) of copies of a net!".format(
                    num_copies))
            raise Exception
        if num_copies < 0:
            logger.error(
                "Can't make a negative number ({}) of copies of a net!".format(
                    num_copies))
            raise Exception

        if self.pins:
            logger.error(
                "Can't make copies of a net that already has pins attached to it!")
            raise Exception

        # Now make copies of the net one-by-one.
        copies = [deepcopy(self) for i in range(num_copies)]

        return list_or_scalar(copies)

    """Make net copies with the multiplication operator."""
    __mul__ = copy
    __rmul__ = copy

    def add_pins(self, *pins):
        for pin in pins:
            if isinstance(pin, Pin):
                if pin not in self.pins:
                    # Pin is not already in the net, so add it to the net.
                    self.pins.append(pin)  # Do 1st or else infinite recursion!
                    pin += self  # Let the pin know the net it's connected to.

                    # Once the first pin is added to a net, it becomes "real"
                    # so add it to the list of nets of the circuit.
                    if len(self.pins) == 1:
                        SubCircuit.add_net(self)

            elif isinstance(pin, (list, tuple)):
                for p in pin:
                    self += p

            else:
                logger.error('Cannot attach a non-Pin {} to Net {}.'.format(
                    type(pin), self.name))
                raise Exception
        return self

    __iadd__ = add_pins

    def erc(self):
        """
        Do electrical rules check on a net in the schematic.
        """

        def pin_conflict_chk(pin1, pin2):
            """
            Check for conflict/contention between two pins on the same net.
            """

            # Use the functions of the two pins to index into the ERC table
            # and see if the pins are compatible (e.g., an input and an output)
            # or incompatible (e.g., a conflict because both are outputs).
            erc_result = SubCircuit.erc_matrix[pin1.func][pin2.func]

            # Return if the pins are compatible.
            if erc_result == SubCircuit.OK:
                return

            # Otherwise, generate an error or warning message.
            msg = 'Pin conflict on net {n}: {p1} <==> {p2}'.format(
                n=pin1.net.name,
                p1=pin1.erc_pin_desc(),
                p2=pin2.erc_pin_desc())
            if erc_result == SubCircuit.WARNING:
                erc_logger.warning(msg)
            else:
                erc_logger.error(msg)

        def net_drive_chk():
            """
            """

            # Find the maximum signal driver on this net.
            net_drive = self.drive  # Start with user-set drive level.
            for p in self.pins:
                net_drive = max(net_drive, Pin.pin_info[p.func]['drive'])

            if net_drive == 0:
                erc_logger.warning('No drivers for net {n}'.format(
                    n=self.name))
            for p in self.pins:
                if Pin.pin_info[p.func]['receive'] > net_drive:
                    erc_logger.warning(
                        'Insufficient drive current on net {n} for pin {p}'.format(
                            n=self.name, p=p.erc_pin_desc()))

        num_pins = len(self.pins)
        if num_pins == 0:
            erc_logger.warning('No pins attached to net {n}.'.format(
                n=self.name))
        elif num_pins == 1:
            erc_logger.warning(
                'Only one pin ({p}) attached to net {n}.'.format(p=self.pins[
                    0].erc_pin_desc(),
                                                                 n=self.name))
        else:
            for i in range(num_pins):
                for j in range(i + 1, num_pins):
                    pin_conflict_chk(self.pins[i], self.pins[j])

        net_drive_chk()

    def generate_netlist_net(self, format='KICAD'):
        """
        Generate the net information for inclusion in a netlist.

        Args:
            format: The format for the netlist file (e.g., 'KICAD').
        """

        def gen_netlist_net_kicad():
            txt = '    (net (code {code}) (name "{name}")'.format(
                code=self.code, name=self.name)
            for p in self.pins:
                txt += '\n      (node (ref {part_ref})(pin {pin_num}))'.format(
                    part_ref=p.part.ref, pin_num=p.num)
            txt += (')')
            return txt

        if format == 'KICAD':
            return gen_netlist_net_kicad()
        else:
            logger.error(
                "Can't generate netlist in an unknown format ({})".format(
                    format))
            raise Exception
            return ''

##############################################################################


class Bus(object):
    def __init__(self, name, *args, **attribs):
        self.set_name(name)
        self.nets = []

        # Build the bus from net widths, existing nets, nets of pins, other buses.
        for arg in args:
            if isinstance(arg, int):
                nets = arg * Net()
                for i, n in enumerate(nets):
                    n.name = self.name + str(i)
                self.nets.extend(nets)
            elif isinstance(arg, Net):
                self.nets.append(arg)
            elif isinstance(arg, Pin):
                self.nets.append(arg.net)
            elif isinstance(arg, Bus):
                self.nets.extend(arg.nets)

        # Attach additional attributes to the bus.
        for k, v in attribs.items():
            setattr(self, k, v)

    def set_name(self, name):
        self.name = name

    def __len__(self):
        return len(self.nets)

    def __getitem__(self, *ids):
        nets = []
        for id in expand_indices(len(self), ids):
            if isinstance(id, int):
                nets.append(self.nets[id])
            elif isinstance(id, type('')):
                nets.extend(filter(self.nets, name=id))
            else:
                logger.error("Can't index bus with a {}.".format(type(id)))
                raise Exception
        if len(nets) == 0:
            return None
        elif len(nets) == 1:
            return nets[0]
        else:
            return Bus('SUBSET', *nets)

    def get_nets(self):
        return to_list(self.nets)

    def get_pins(self):
        logger.error("Can't get the list of pins on a bus!")
        raise Exception

    def connect(self, *pin_net_bus):
        nets = []
        for item in unnest_list(pin_net_bus):
            if isinstance(item, Pin):
                nets.append(item)
            elif isinstance(item, Net):
                nets.append(item)
            elif isinstance(item, Bus):
                nets.extend(item.nets)
            else:
                logger.error("Can't connect a {} {} to a bus.".format(
                    type(id), item.__name__))
                raise Exception

        if len(nets) != len(self):
            logger.error("Bus connection mismatch.")
            raise Exception

        for i, net in enumerate(nets):
            self.nets[i] += net

        return self

    __iadd__ = connect

    def __setitem__(self, ids, *pin_net_bus):
        """
        Connect nets or pins of other parts to the specified bus lines.

        Args:
            bus_lines: List of indices for individual bus lines.
            nets: Nets, pins or buses to be connected.

        Raises:
            Exception if the list of pins to connect to is empty.
        """
        return self

##############################################################################


class SubCircuit(object):
    """
    Class object that holds the entire netlist of parts and nets. This is
    initialized once when the module is first imported and then all parts
    and nets are added to its static members.

    Static Attributes:
        circuit_parts: List of all the schematic parts as Part objects.
        circuit_nets: List of all the schematic nets as Net objects.
        hierarchy: A '.'-separated concatenation of the names of nested
            SubCircuits at the current time it is read.
        level: The current level in the schematic hierarchy.
        context: Stack of contexts for each level in the hierarchy.

    Attributes:
        circuit_func: The function that creates a given subcircuit.
    """

    OK, WARNING, ERROR = range(3)

    circuit_parts = []
    circuit_nets = []
    hierarchy = 'top'
    level = 0
    context = [('top', )]

    @classmethod
    def reset(cls):
        """Clear any circuitry and start over."""
        cls.circuit_parts = []
        cls.circuit_nets = []
        cls.hierarchy = 'top'
        cls.level = 0
        cls.context = [('top', )]

    @classmethod
    def add_part(cls, part):
        """Add a Part object to the circuit"""
        part.ref = part.ref  # This adjusts the part reference if necessary.
        part.hierarchy = cls.hierarchy  # Tag the part with its hierarchy position.
        cls.circuit_parts.append(part)

    @classmethod
    def add_net(cls, net):
        """Add a Net object to the circuit. Assign a net name if necessary."""
        net.name = net.name
        #cls.name_net(net)
        net.hierarchy = cls.hierarchy  # Tag the net with its hierarchy position.
        cls.circuit_nets.append(net)

    def __init__(self, circuit_func):
        '''
        When you place the @SubCircuit decorator before a function, this method
        stores the reference to the subroutine into the SubCircuit object.
        '''

        self.circuit_func = circuit_func

    def __call__(self, *args, **kwargs):
        """
        This method is called when you invoke the SubCircuit object to create
        some schematic circuitry.
        """

        # Invoking the SubCircuit object creates circuitry at a level one
        # greater than the current level. (The top level is zero.)
        self.level += 1

        # Create a name for this SubCircuit from the concatenated names of all
        # the SubCircuit functions that were called on all the preceding levels
        # that led to this one.
        self.__class__.hierarchy = self.context[-1][
            0] + '.' + self.circuit_func.__name__

        # Store the context so it can be used if this SubCircuit object
        # invokes another SubCircuit object within itself to add more
        # levels of hierarchy.
        self.context.append((self.__class__.hierarchy, ))

        # Call the SubCircuit object function to create whatever circuitry it handles.
        # The arguments to the function are usually nets to be connected to the
        # parts instantiated in the function, but they may also be user-specific
        # and have no effect on the mechanics of adding parts or nets although
        # they may direct the function as to what parts and nets get created.
        # Store any results it returns as a list. These results are user-specific
        # and have no effect on the mechanics of adding parts or nets.
        try:
            results = list_or_scalar(self.circuit_func(*args, **kwargs))
        except:
            logger.exception("Serious error! Can't continue.")

        # Restore the context that existed before the SubCircuit circuitry was
        # created. This does not remove the circuitry since it has already been
        # added to the circuit_parts and circuit_nets lists.
        self.context.pop()

        return results

    @classmethod
    def erc_setup(cls):
        """
        Initialize the electrical rules checker.
        """

        # Initialize the pin conention matrix.
        cls.erc_matrix = [[cls.OK for c in range(11)] for r in range(11)]
        cls.erc_matrix[Pin.OUTPUT][Pin.OUTPUT] = cls.ERROR
        cls.erc_matrix[Pin.TRISTATE][Pin.OUTPUT] = cls.WARNING
        cls.erc_matrix[Pin.UNSPEC][Pin.INPUT] = cls.WARNING
        cls.erc_matrix[Pin.UNSPEC][Pin.OUTPUT] = cls.WARNING
        cls.erc_matrix[Pin.UNSPEC][Pin.BIDIR] = cls.WARNING
        cls.erc_matrix[Pin.UNSPEC][Pin.TRISTATE] = cls.WARNING
        cls.erc_matrix[Pin.UNSPEC][Pin.PASSIVE] = cls.WARNING
        cls.erc_matrix[Pin.UNSPEC][Pin.UNSPEC] = cls.WARNING
        cls.erc_matrix[Pin.PWRIN][Pin.TRISTATE] = cls.WARNING
        cls.erc_matrix[Pin.PWRIN][Pin.UNSPEC] = cls.WARNING
        cls.erc_matrix[Pin.PWROUT][Pin.OUTPUT] = cls.ERROR
        cls.erc_matrix[Pin.PWROUT][Pin.BIDIR] = cls.WARNING
        cls.erc_matrix[Pin.PWROUT][Pin.TRISTATE] = cls.ERROR
        cls.erc_matrix[Pin.PWROUT][Pin.UNSPEC] = cls.WARNING
        cls.erc_matrix[Pin.PWROUT][Pin.PWROUT] = cls.ERROR
        cls.erc_matrix[Pin.OPENCOLL][Pin.OUTPUT] = cls.ERROR
        cls.erc_matrix[Pin.OPENCOLL][Pin.TRISTATE] = cls.ERROR
        cls.erc_matrix[Pin.OPENCOLL][Pin.UNSPEC] = cls.WARNING
        cls.erc_matrix[Pin.OPENCOLL][Pin.PWROUT] = cls.ERROR
        cls.erc_matrix[Pin.OPENEMIT][Pin.OUTPUT] = cls.ERROR
        cls.erc_matrix[Pin.OPENEMIT][Pin.BIDIR] = cls.WARNING
        cls.erc_matrix[Pin.OPENEMIT][Pin.TRISTATE] = cls.WARNING
        cls.erc_matrix[Pin.OPENEMIT][Pin.UNSPEC] = cls.WARNING
        cls.erc_matrix[Pin.OPENEMIT][Pin.PWROUT] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.INPUT] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.OUTPUT] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.BIDIR] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.TRISTATE] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.PASSIVE] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.UNSPEC] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.PWRIN] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.PWROUT] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.OPENCOLL] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.OPENEMIT] = cls.ERROR
        cls.erc_matrix[Pin.NOCONNECT][Pin.NOCONNECT] = cls.ERROR

        # Fill-in the other half of the symmetrical matrix.
        for c in range(1, 11):
            for r in range(c):
                cls.erc_matrix[r][c] = cls.erc_matrix[c][r]

        # Setup the error/warning logger.
        global erc_logger
        erc_logger = logging.getLogger('ERC_Logger')
        log_level = logging.WARNING
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(log_level)
        handler.setFormatter(logging.Formatter(
            'ERC %(levelname)s: %(message)s'))
        erc_logger.addHandler(handler)
        erc_logger.setLevel(log_level)
        erc_logger.error = count_calls(erc_logger.error)
        erc_logger.warning = count_calls(erc_logger.warning)

    @classmethod
    def ERC(cls):
        """
        Do an electrical rules check on the circuit.
        """

        cls.erc_setup()

        # Check the nets for errors.
        for net in cls.circuit_nets:
            net.erc()

        # Check the parts for errors.
        for part in cls.circuit_parts:
            part.erc()

        if (erc_logger.error.count, erc_logger.warning.count) == (0, 0):
            logger.info('No errors or warnings found.')

    @classmethod
    def generate_netlist(cls, filename, format='KICAD'):

        if format == 'KICAD':
            scr_dict = scriptinfo()
            src_file = os.path.join(scr_dict['dir'], scr_dict['source'])
            date = time.strftime('%m/%d/%Y %I:%M %p')
            tool = 'SchDL (' + __version__ + ')'

            print('''(export (version D)
  (design
    (source "{src_file}")
    (date "{date}")
    (tool "{tool}"))'''
                  .format(src_file=src_file,
                          date=date, tool=tool))
            print("  (components")
            for p in SubCircuit.circuit_parts:
                comp_txt = p.generate_netlist_component(format)
                print(comp_txt)
            print("  )")
            print("  (nets")
            for code, n in enumerate(SubCircuit.circuit_nets):
                n.code = code
                net_txt = n.generate_netlist_net(format)
                print(net_txt)
            print("  )")
            print(")")


def scriptinfo():
    '''
    Returns a dictionary with information about the running top level Python
    script:
    ---------------------------------------------------------------------------
    dir:    directory containing script or compiled executable
    name:   name of script or executable
    source: name of source code file
    ---------------------------------------------------------------------------
    "name" and "source" are identical if and only if running interpreted code.
    When running code compiled by py2exe or cx_freeze, "source" contains
    the name of the originating Python script.
    If compiled by PyInstaller, "source" contains no meaningful information.

    Downloaded from:
    http://code.activestate.com/recipes/579018-python-determine-name-and-directory-of-the-top-lev/
    '''

    import os, sys, inspect
    #---------------------------------------------------------------------------
    # scan through call stack for caller information
    #---------------------------------------------------------------------------
    for teil in inspect.stack():
        # skip system calls
        if teil[1].startswith("<"):
            continue
        if teil[1].upper().startswith(sys.exec_prefix.upper()):
            continue
        trc = teil[1]

    # trc contains highest level calling script name
    # check if we have been compiled
    if getattr(sys, 'frozen', False):
        scriptdir, scriptname = os.path.split(sys.executable)
        return {"dir": scriptdir, "name": scriptname, "source": trc}

    # from here on, we are in the interpreted case
    scriptdir, trc = os.path.split(trc)
    # if trc did not contain directory information,
    # the current working directory is what we need
    if not scriptdir:
        scriptdir = os.getcwd()

    scr_dict = {"name": trc, "source": trc, "dir": scriptdir}
    return scr_dict
