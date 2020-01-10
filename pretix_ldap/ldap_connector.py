from ldap3 import Server, Connection
import re
import logging
from django import forms
from django.utils.translation import ugettext_lazy as _
from pretix.settings import config
from pretix.base.auth import BaseAuthBackend


logger = logging.getLogger(__name__)


class LDAPAuthBackend(BaseAuthBackend):
    def __init__(self):
        try:
            self.config = config['ldap']
            self.server = Server(self.config['bind_url'])
            self.connection = Connection(self.server, self.config['bind_dn'], self.config['bind_password'], auto_bind=True)
            self.search_base = self.config['search_base']
        except KeyError:
            logger.error("please specify bind_url, bind_dn, bind_password, and search_base in [ldap] section in pretix.cfg")
        self.search_filter_template = self.config.get('search_filter', fallback='(&(objectClass=inetOrgPerson)(mail={email}))')
        self.email_attr = self.config.get('email_attr', fallback='mail')


    @property
    def identifier(self):
        return 'pretix_ldap'


    @property
    def verbose_name(self):
        return 'LDAP Authentication'


    @property
    def login_form_fields(self):
        placeholders = re.findall('\{([^{}]+)\}', self.search_filter_template)
        fields = {p : forms.CharField(label=p) for p in placeholders}
        fields['password'] = forms.CharField(label=_('Password'), widget=forms.PasswordInput)
        return fields


    def form_authenticate(self, request, form_data):
        from pretix.base.models import User
        password = form_data['password']
        filter = self.search_filter_template.format_map(form_data) # TODO escape
        if not self.connection.search(self.search_base, filter, attributes = [self.email_attr]):
            # user not found
            return None
        res = self.connection.response
        if len(res) != 1:
            # could not uniquely identify user
            return None
        dn = res[0]['dn']
        emails = res[0]['attributes'][self.email_attr]
        if len(emails) != 1:
            # could not uniquely identify user email
            return None
        email = emails[0]
        try:
            success = self.connection.rebind(user=dn,password=password)
        except:
            success = False
        self.connection.rebind(self.config['BIND_DN'],self.config['BIND_PASSWORD'])
        if not success:
            # wrong password
            return None
        try:
            user = User.objects.get(email=email)
            if user.auth_backend == self.identifier:
                return user
            else:
                # user already registered with different backend
                return None
        except User.DoesNotExist:
            # user does not exist yet -> create new
            user = User(email=email)
            user.auth_backend = self.identifier
            user.save()
            return user