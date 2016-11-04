import os
import re
import datetime
import json
from enum import Enum
from iso8601utils.parsers import datetime as iso8601


def _get_latest_export():
    ranch_dir = os.path.dirname(os.path.split(__file__)[0])
    data_dir = os.path.join(ranch_dir, 'data')

    latest_file = ''
    latest_time = datetime.datetime(1970, 1, 1)
    for item in os.listdir(data_dir):
        if not item.startswith('address-export.'):
            continue

        time = iso8601(os.path.splitext(item)[0][len('address-export.'):])
        if time > latest_time:
            latest_time = time
            latest_file = item

    return os.path.join(data_dir, latest_file)


def _get_default_specs():
    with open(_get_latest_export(), 'r') as data:
        specs = json.load(data)
    return specs


class AddressParts(Enum):
    """An enum containing all possible values for address parts"""
    name = 'N'
    organisation = 'O'
    street_address = 'A'
    dependent_locality = 'D'
    city = 'C'
    admin_area = 'S'
    postal_code = 'Z'
    sorting_code = 'X'

    # Country is special, since we made up this character ourselves.
    country = '0'

    @classmethod
    def significant(cls):
        """
        An ordered, reversed list of parts, so that the first item is the
        largest topological division. This also strips out postal and sorting
        code, since they're independent from all the others.
        """
        ordered_values = cls.__members__.values()
        reverse = reversed(list(ordered_values))
        return list(filter(lambda p: not p.name.endswith('_code'), reverse))


class InvalidAddressException(ValueError):
    pass


class FieldValue(object):
    def __init__(self, value, details, subs):
        self.value = value
        self.details = details
        self.subs = subs


class Address(object):
    """An address value.

    The Address class can save and validate a full address, from any of the
    countries specified in the specifications passed to it. These
    specifications should be generated by the generate.download module, as they
    adhere to Google's i18n imported values.

    Mostly, you'll want to use the `get_data()`, `get_field_types()` and
    `set_field()` methods. These three methods should allow you to create a
    form that dynamically responds to any data and shows only relevant form
    fields. You can then simply call `str(address)` to get a fully valid
    address string, which you could use to send emails, for example.
    """

    def __init__(self, specs=_get_default_specs(), values=None):
        self.specs = specs
        self.defaults = FieldValue('', specs['details'], specs['subs'])

        self.fields = {}
        if values is not None:
            values_sorted = sorted(
                filter(lambda f: not f[0].name.endswith('_code'),
                       values.items()),
                key=lambda i: AddressParts.significant().index(i[0])
            )
            values_sorted += filter(lambda f: f[0].name.endswith('_code'),
                                    values.items())

            for field, value in values_sorted:
                self.set_field(field, value)

    def field_in_fmt(self, part):
        if part == AddressParts.country:
            return True

        data = self.get_specs()
        return '%{0}'.format(part.value) in data['fmt']

    def index_in_fmt(self, query_part):
        fmt = self.get_specs()['fmt']

        fmt_fields = []
        for substr in fmt.split('%')[1:]:
            c = substr[0]
            for part in AddressParts:
                if part.value == c:
                    fmt_fields.append(part)
                    break

        fmt_fields.append(AddressParts.country)

        return fmt_fields.index(query_part)

    def get_significant_fields(self):
        """
        Get a list of (key, value) objects of fields sorted by
        significance.
        """
        return sorted(
            filter(lambda f: not f[0].name.endswith('_code'),
                   self.fields.items()),
            key=lambda i: AddressParts.significant().index(i[0])
        )

    def get_specs(self):
        """Get an up-to-date list of specifications for the address.

        This returns a specs dict, based on the details of the filled in fields
        but falling back to the defaults from the specs. It takes the specs
        from the least significant field.
        """
        specs = self.defaults.details

        for field, value in self.get_significant_fields():
            specs.update(value.details)

        return specs

    def get_field_types(self):
        """Gets a list of currently known-about fields."""
        fields = []
        # add the country now, since it's always the first field to fill in
        fields.append({
            'key': AddressParts.country,
            'label': 'country',
            'required': True,
            'options': {key: value['details'].get('name', key)
                        for key, value in self.defaults.subs.items()
                        if '--' not in key},
        })
        data = self.get_specs()

        if 'fmt' not in data:
            return fields

        # we want only parts we have, by significance
        sig = [part for part in AddressParts.significant()
               if self.field_in_fmt(part)]

        for depth, part in enumerate(sig):
            # already have this
            if part == AddressParts.country:
                continue

            # we want to know if the "parent field" has choices for this field
            # because if it does, but no option is chosen yet, we can'ts how
            # the other fields
            options = None
            parent = depth - 1
            parent_part = sig[parent]

            if fields[parent]['options'] is not None and \
               parent_part not in self.fields:
                break

            # otherwise, if it is filled in, we only need to see if it has
            # options
            elif parent_part in self.fields:
                relevant = self.fields[parent_part]
                if len(relevant.subs) > 0:
                    options = {key: value['details'].get('name', key)
                               for key, value in relevant.subs.items()
                               if '--' not in key}

            if part == AddressParts.admin_area:
                label = relevant.details.get('state_name_type', 'province')
            else:
                label = part.name.replace('_', ' ')

            fields.append({
                'key': part,
                'required': part.value in data['require'],
                'label': label,
                'options': options,
            })
        else:
            require = data['require']
            if self.field_in_fmt(AddressParts.postal_code):
                fields.append({
                    'key': AddressParts.postal_code,
                    'required': AddressParts.postal_code.value in require,
                    'label': 'postal code',
                    'options': None,
                })
            if self.field_in_fmt(AddressParts.sorting_code):
                fields.append({
                    'key': AddressParts.sorting_code,
                    'required': AddressParts.sorting_code.value in require,
                    'label': 'sorting code',
                    'options': None,
                })

        # Sort the fields so that all fields with choices end up at the top,
        # and the other fields are sorted by their position in the output
        # format.
        sort = sorted(
            fields,
            key=lambda f: (-len(fields) + fields.index(f)
                           if f['options'] is not None
                           else self.index_in_fmt(f['key']))
        )

        return sort

    def get_detail(self, field, prop):
        """
        Gets the value of a detail property for a certain field, but falls back
        to the defaults.
        """
        details = self.fields[field].details
        return details.get(prop, self.defaults.details.get(prop, None))

    def set_field(self, field, value):
        chosen = {}

        sig = AddressParts.significant()
        try:
            depth = sig.index(field)
        except ValueError:
            depth = -1

        if depth == 0:
            relevant_part = sig[0]
            relevant = self.defaults
        elif depth > 0:
            relevant_part = sig[depth - 1]
            if relevant_part not in self.fields:
                relevant = False
            else:
                relevant = self.fields[relevant_part]

        if depth > -1 and relevant and \
           (depth == 0 or 'sub_keys' in relevant.details):
            if value not in relevant.subs:
                raise InvalidAddressException(
                    '"{0}" is not a valid value for field {1}'
                    .format(value, field.name)
                )

            chosen = relevant.subs[value]

        if not self.validate_field(field, value):
            raise InvalidAddressException(
                '"{0}" is not a valid value for field "{1}"'
                .format(value, field)
            )
        if AddressParts.postal_code == field:
            if not self.validate_postal_code(value):
                raise InvalidAddressException('Invalid postal code')

        fv = FieldValue(
            value=value,
            details=chosen.get('details', {}),
            subs=chosen.get('subs', {})
        )

        # Clear out all fields below this one if the old value had options
        if field in self.fields and len(self.fields[field].subs) > 0 and \
           depth > -1:
            parts = AddressParts.significant()
            parts += filter(lambda p: p.name.endswith('_code'), AddressParts)

            new_fields = {}
            index = parts.index(field)
            for f in self.fields:
                if parts.index(f) <= index:
                    new_fields[f] = self.fields[f]

            self.fields = new_fields

        self.fields[field] = fv

        if AddressParts.postal_code in self.fields:
            if not self.validate_postal_code():
                raise InvalidAddressException('Invalid postal code')

    def validate_postal_code(self, postal_code=None):
        if postal_code is None:
            if AddressParts.postal_code not in self.fields:
                return False

            postal_code = self.fields[AddressParts.postal_code].value

        regex = self.get_detail(AddressParts.country, 'zip')
        if not re.fullmatch(regex, postal_code):
            return False

        for value in self.fields.values():
            if 'zip' not in value.details:
                continue

            regex = value.details['zip']
            if not re.match(regex, postal_code):
                return False

        return True

    def validate_field(self, field, value):
        data = self.get_specs()

        return field.value not in data['require'] or \
            value is not None and value != ''

    def is_valid(self):
        data = self.get_specs()

        set_fields = ''.join(f.value for f in self.fields)
        fields_required = [r in set_fields for r in data['require']]

        fields_valid = [self.validate_field(part, value.value)
                        for part, value in self.fields.items()]
        code_valid = self.validate_postal_code()

        return all(fields_required) and all(fields_valid) and code_valid

    def __str__(self):
        data = self.get_specs()
        out = data['fmt']

        out = out.replace('%n', "\n")

        # replace each part by its value
        for part in AddressParts.__members__.values():
            # unless it doesn't exist
            if part not in self.fields:
                if part.value in data['require']:
                    raise KeyError('No value set for required field {0}'
                                   .format(part.name))

                out = out.replace('%{0}'.format(part.value), '')
                continue

            # possibly needs to be uppercase too
            val = self.fields[part].value
            if part.value in data['upper']:
                val = val.upper()

            out = out.replace('%{0}'.format(part.value), val)

        # append the country to the end
        out += "\n" + self.fields[AddressParts.country].details['name']

        # remove blank lines
        out = "\n".join(l.rstrip() for l in out.splitlines() if l.strip())

        return out
