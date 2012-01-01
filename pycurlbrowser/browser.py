# Copyright (C) Adam Piper, 2012
# See COPYING for licence details (GNU AGPLv3)

"""
A python web browser for scraping purposes.
Includes canned responses for testing.
"""

import pycurl
import StringIO
from lxml.html import fromstring
from urllib import urlencode
from datetime import datetime, timedelta

def check_curl(item):
    """Convenience method to check whether curl supports a given feature"""
    return item in pycurl.version_info()[8]

def escape_data(data, escaped):
    """Escape data if neccessary"""
    if data is not None and not escaped:
        data = urlencode(data)

    return data

def post_data_present(d_ref, d_in):
    """Make sure that every element of d_ref exists in d_in"""
    setify = lambda s: set(s.split('&'))
    return len(setify(d_ref) - setify(d_in)) == 0

def post_best_fit(d_in, *d_ref):
    """Return the best fitting data"""
    comp = len(d_in)
    diffs = dict()
    for d in d_ref:
        if not post_data_present(d, d_in):
            continue

        diffs[d] = abs(len(d) - comp)

    # sort by diffs values
    e = diffs.keys()
    e.sort(cmp=lambda a, b: cmp(diffs[a], diffs[b]))

    try:
        return e[0]
    except IndexError:
        raise IndexError("Could not choose from zero options for input data: %s" % d_in)

def canned_key_partial_subset(matcher, sample):
    """Match the first two elements of each tuple in sample to the matcher"""
    return [k[2] for k in sample if matcher == k[0:2]]

def select_best_can(url, method, data, cans):
    """Given a dict of cans, try to give the best match"""
    if data is None:
        return cans[url, method, data]

    return cans[url,
                method,
                post_best_fit(data,
                              *canned_key_partial_subset((url, method),
                                                         cans.keys()))]

class CannedResponse(object):

    """
    A fictional response predominantly for testing purposes
    """

    def __init__(self):
        """Set up some defaults"""
        self.code = 200
        self.exception = None
        self.roundtrip = timedelta()
        self.src = ''

class Browser(object):

    """
    Emulate a normal browser

    This class is a convenience on top of libcurl and lxml; it should behave
    like a normal browser (but lacking Javascript), and allow DOM queries.
    """

    def __init__(self, url=None):
        self.retries = 0
        self._curl = pycurl.Curl() # note: this is an "easy" connection
        self.set_follow(True) # follow location headers
        self._curl.setopt(pycurl.AUTOREFERER, 1)
        self._curl.setopt(pycurl.MAXREDIRS, 20)
        self._curl.setopt(pycurl.ENCODING, "gzip")
        self._buf = StringIO.StringIO()
        self._curl.setopt(pycurl.WRITEFUNCTION,
                          self._buf.write) # callback for content buffer
        self._curl.setopt(pycurl.USERAGENT,
                          "Mozilla/5.0 (X11; Linux i686) " +\
                          "AppleWebKit/534.24 (KHTML, like Gecko) " +\
                          "Ubuntu/10.10 Chromium/11.0.696.65 " +\
                          "Chrome/11.0.696.65 Safari/534.24")
        self._curl.setopt(pycurl.COOKIEFILE, "") # use cookies
        self._curl.setopt(pycurl.CONNECTTIMEOUT, 2)
        self._curl.setopt(pycurl.TIMEOUT, 4)
        self._canned_responses = dict()
        self.reset()

        self.canned_url = None
        self.offline = False

        if url is not None:
            self.go(url)

    def reset(self):
        """Clear out the browser state"""
        self._tree = None
        self._form = None
        self._form_data = {}
        self._roundtrip = None

    roundtrip = property(lambda self: self._roundtrip)

    def add_canned_response(self, can, url, method='GET',
                                  data=None, escaped=False):
        """Add canned responses, for testing purposes"""
        data = escape_data(data, escaped)

        self._canned_responses[url, method, data] = can

    def _setup_data(self, url, method, data, escaped):
        """Escape the data and configure curl based upon the method"""
        data = escape_data(data, escaped)

        self._curl.setopt(pycurl.CUSTOMREQUEST, method)
        if data is not None:
            if method == 'GET':
                sep = '&' if '?' in url else '?'
                url = "%(current)s%(sep)s%(data)s" % {'current': url,
                                                      'sep'    : sep,
                                                      'data'   : data}
            else:
                self._curl.setopt(pycurl.POSTFIELDS, data)

        return url, data

    def _setup_canned_response(self, can, url):
        """Setup state based upon a canned response"""
        self._buf.write(can.src)
        self.reset()
        self._roundtrip = can.roundtrip
        self.canned_url = url
        return can.code

    def _setup_http_response(self, url):
        """Setup state based upon an HTTP request"""
        self._curl.setopt(pycurl.URL, url)

        before = datetime.now()
        retries = self.retries
        exception = Exception("Dummy exception")

        while retries >= 0 and exception is not None:
            retries -= 1
            try:
                self._curl.perform()
                exception = None
            except pycurl.error, ex:
                exception = ex

        if exception is not None:
            raise exception

        self.reset()
        self._roundtrip = datetime.now() - before
        return self._curl.getinfo(pycurl.RESPONSE_CODE)

    def go(self, url, method='GET', data=None, escaped=False):
        """Go to a url"""
        # set up some variables
        self._buf.truncate(0)
        method = method.upper()

        # sometimes the url might change to accomodate data
        url, data = self._setup_data(url, method, data, escaped)

        # ideally we don't need to traverse the network
        try:
            can = select_best_can(url, method, data, self._canned_responses)
            if can.exception is not None:
                raise can.exception

            return self._setup_canned_response(can, url)
        except KeyError:
            if self.offline:
                raise LookupError("In offline mode, but no match for %s in canned response list: %s"\
                        % ((url, method, data), self._canned_responses.keys()))

            return self._setup_http_response(url)

    def save(self, filename):
        """Save the current page"""
        with open(filename, 'w') as fp:
            fp.write(self.src)

    def save_pretty(self, filename):
        """Save the current page, after lxml has prettified it"""
        self.parse()
        from lxml.builder import ET
        with open(filename, 'w') as fp:
            fp.write(ET.tostring(self._tree, pretty_print=True))

    def parse(self):
        """Parse the current page into a node tree"""
        if self._tree is not None:
            return

        self._tree = fromstring(self.src)
        self._tree.make_links_absolute(self._curl.getinfo(pycurl.EFFECTIVE_URL))

    # form selection/submission

    def form_select(self, idx):
        """Select a form on the current page"""
        self.parse()
        try:
            self._form = self._tree.forms[idx]
        except TypeError:
            # perhaps we've been given a name/id
            if idx is None:
                raise
            self._form = self._tree.forms[[f for f in self.forms
                                           if idx in
                                              (f.get('name'),
                                               f.get('id'))][0]['__number']]

        self._form_data = dict(self.form_fields)

        # set the default values for all dropdowns in this form
        for d in self.form_dropdowns:
            self.form_fill_dropdown(d)

    def form_data_update(self, **kwargs):
        """Check that a form is selected, and update the state"""
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms
        self._form_data.update(kwargs)

    def _form_dropdown_options_raw(self, select_name):
        """Get the options for a dropdown"""
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms
        return self._form.xpath('.//select[@name="%s"]//option' % select_name)

    def form_dropdown_options(self, select_name):
        """List options for the given dropdown"""
        return dict(((o.text, o.get('value')) for o in
                    self._form_dropdown_options_raw(select_name)))

    def form_fill_dropdown(self, select_name, option_title=None):
        """Fill the value for a dropdown"""

        nodes = self._form_dropdown_options_raw(select_name)
        if option_title is None:
            node = nodes[0]
        else:
            node = [n for n in nodes if n.text == option_title][0]

        self.form_data_update(**{select_name:node.get('value')})

    def form_submit(self, submit_button=None):
        """
        Submit the currently selected form with the given (or the first)
        submit button.
        """
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms

        submits = self.form_submits
        assert len(submits) <= 1 or submit_button is not None, \
                               "Implicit submit is not possible; " + \
                               "an explicit choice must be passed: %s" % submits
        if len(submits) > 0:
            try:
                submit = submits[0 if submit_button is None else submit_button]
            except TypeError:
                # perhaps we've been given a name/id
                submit = submits[[s for s in submits
                                  if submit_button in
                                      s.values()][0]['__number']]

            if 'name' in submit:
                self.form_data_update(**{submit['name']: submit['value']
                                                         if 'value' in submit
                                                         else ''})

        action = self._form.action if   self._form.action is not None\
                                   else self.url

        return self.form_submit_data(self._form.method,
                                     action,
                                     self._form_data)

    def form_submit_no_button(self):
        """
        Submit the currently selected form, but don't use a button to do it.
        """
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms
        return self.form_submit_data(self._form.method,
                                     self._form.action,
                                     self._form_data)

    def form_submit_data(self, method, action, data):
        """Submit data, intelligently, to the given action URL"""
        assert method is not None, "method must be supplied"
        assert action is not None, "action must be supplied"
        return self.go(action, method, data)

    def follow_link(self, name_or_xpath):
        """Emulate clicking a link"""
        if name_or_xpath[0] == '/':
            xpath = name_or_xpath
        else:
            xpath = '//a[text()="%s"]' % name_or_xpath
        link = self.xpath(xpath)[0]
        return self.go(link.get('href'))

    # helpers

    @property
    def src(self):
        """Read-only page-source"""
        return self._buf.getvalue()

    @property
    def url(self):
        """Read-only current URL"""
        if self.canned_url is not None:
            return self.canned_url

        return self._curl.getinfo(pycurl.EFFECTIVE_URL)

    @property
    def title(self):
        """Read-only convenience for getting the HTML title"""
        self.parse()
        try:
            return self._tree.xpath("/html/head/title/text()")[0].strip()
        except IndexError:
            return None

    @property
    def forms(self):
        """Convenience for grabbing the HTML form nodes"""
        self.parse()
        forms = []
        for i, form in enumerate(self._tree.forms):
            items = {'__number': i}
            for name, value in form.items():
                if name in ('name', 'id', 'class'):
                    items[name] = value
            forms.append(items)
        return forms

    @property
    def form_dropdowns_nodes(self):
        """Names of dropdowns for selected form"""
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms
        return self._form.xpath('.//select')

    @property
    def form_dropdowns(self):
        """Names of dropdowns for selected form"""
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms
        return (s.get('name') for s in self.form_dropdowns_nodes)

    @property
    def form_fields(self):
        """Dict of fields and values for selected form"""
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms
        return dict((pair for pair in self._form.fields.items()
                          if pair[0] != ''))

    @property
    def form_submits(self):
        """Dict of submits for selected form"""
        assert self._form is not None, \
            "A form must be selected: %s" % self.forms

        submit_lst = self._form.xpath(".//input[@type='submit']")
        assert len(submit_lst) > 0, \
            "The selected form must contain a submit button"

        submits = []
        for i, submit in enumerate(submit_lst):
            items = {'__number': i}
            for name, value in submit.items():
                if name in ('name', 'value'):
                    items[name] = value
            submits.append(items)
        return submits

    def xpath(self, *argv, **kwargs):
        """Execute an XPATH against the current node tree"""
        self.parse()
        return self._tree.xpath(*argv, **kwargs)

    def set_follow(self, switch):
        """
        Indicate whether the browser should automatically follow
        redirect headers.
        """
        self._curl.setopt(pycurl.FOLLOWLOCATION, 1 if switch else 0)

    def set_debug(self, switch):
        """Set debug mode on or off"""
        def debug(typ, msg):
            """Closure to pass in that makes debug info more readable"""
            indicators = {pycurl.INFOTYPE_TEXT:       '%',
                          pycurl.INFOTYPE_HEADER_IN:  '<',
                          pycurl.INFOTYPE_HEADER_OUT: '>',
                          pycurl.INFOTYPE_DATA_OUT:   '>>'}
            if typ in indicators.keys():
                print "%(ind)s %(msg)s" % {'ind': indicators[typ],
                                           'msg': msg.strip()}

        self._curl.setopt(pycurl.VERBOSE, 1 if switch else 0)
        self._curl.setopt(pycurl.DEBUGFUNCTION, debug)
