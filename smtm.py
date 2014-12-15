import sys
sys.path.insert(0, 'lib')

import flask
from flask.ext import restful
from flask.ext.restful import reqparse
from functools import wraps
from google.appengine.api import users
from google.appengine.ext import ndb
import datetime

app = flask.Flask(__name__)
api = restful.Api(app)

class Message:
    ERR_NOT_AUTH        = {'error': 'Not authenticated'}, 400 # Or 401?
    ERR_NO_ENTITY       = {'error': 'Entity not found'}, 404
    ERR_ENTITY_EXISTS   = {'error': 'Entity already exists'}, 409
    ERR_CONFLICT        = {'error': 'Property conflict'}, 409
    ERR_MALFORMED       = {'error': 'Malformed request'}, 400
    NO_CONTENT          = None, 204

class NDBPlace(ndb.Model):
    name        = ndb.StringProperty(required=True)
    icon        = ndb.StringProperty()
    aliases     = ndb.StringProperty(repeated=True)

class NDBAccount(ndb.Model):
    user        = ndb.StringProperty(required=True)
    name        = ndb.StringProperty(required=True)

    def asDict(self):
        d = {}
        d['key']  = self.key.urlsafe()
        d['name'] = self.name

        return d

class NDBCategory(ndb.Model):
    user        = ndb.StringProperty(required=True)
    name        = ndb.StringProperty(required=True)

class NDBSubcategory(ndb.Model):
    user        = ndb.StringProperty(required=True)
    category    = ndb.KeyProperty(required=True)
    name        = ndb.StringProperty(required=True)

class NDBTransaction(ndb.Model):
    user        = ndb.StringProperty(required=True)
    date        = ndb.DateProperty(required=True)
    amount      = ndb.IntegerProperty(required=True)
    payeer      = ndb.StringProperty()
    account     = ndb.KeyProperty(required=True)
    description = ndb.StringProperty(indexed=False)
    pair        = ndb.KeyProperty()
    category    = ndb.KeyProperty() # Category or subcategory

    def asDict(self):
        d = {}
        d['key']         = self.key.urlsafe()
        d['date']        = str(self.date)
        d['amount']      = self.amount
        d['account']     = self.account.urlsafe()

        if self.payeer is not None:
            d['payeer']      = self.payeer

        if self.description is not None:
            d['description'] = self.description

        if self.pair is not None:
            d['pair']       = self.pair.urlsafe()

        if self.category is not None:
            d['category']   = self.category.urlsafe()

        return d

def retrieveEntry(keyStr, kinds=None, user=None):
    key = ndb.Key(urlsafe=keyStr)

    if kinds is not None and key.kind() not in [k.__name__ for k in kinds]:
        raise Exception

    entry = key.get()

    if user is not None and entry.user != user:
        raise Exception

    return entry

def authRequired(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not users.get_current_user():
            return Message.ERR_NOT_AUTH
        return func(*args, **kwargs)
    return decorated

class SingleResource(object):
    @staticmethod
    def get(key, kind):
        user = users.get_current_user().user_id()
        try:
            return retrieveEntry(key, (kind,), user).asDict()
        except:
            return Message.ERR_NO_ENTITY

    @staticmethod
    def delete(key, kind):
        user = users.get_current_user().user_id()
        try:
            retrieveEntry(key, (kind,), user).key.delete()
            return Message.NO_CONTENT
        except:
            return Message.ERR_NO_ENTITY

class Account(restful.Resource):
    decorators = [authRequired]

    def get(self, key):
        return SingleResource.get(key, NDBAccount)

    def delete(self, key):
        return SingleResource.delete(key, NDBAccount)

    def put(self, key):
        r = reqparse.RequestParser()
        r.add_argument('name', type=str, required=True, location='json')
        args = r.parse_args()

        try:
            acc = retrieveEntry(key, (NDBAccount,))
        except:
            return Message.ERR_NO_ENTITY

        acc.name = args['name']
        acc.key.put()
        return acc.asDict(), 200

class Transaction(restful.Resource):
    decorators = [authRequired]

    def get(self, key):
        return SingleResource.get(key, NDBTransaction)

    def delete(self, key):
        return SingleResource.delete(key, NDBTransaction)

class ListResource(object):
    @staticmethod
    def get(name, kind):
        user = users.get_current_user().user_id()
        entries = kind.query(kind.user==user).fetch()
        return {name: [e.asDict() for e in entries]}

class AccountList(restful.Resource):
    decorators = [authRequired]

    def get(self):
        return ListResource.get('accounts', NDBAccount)

    def post(self):
        r = reqparse.RequestParser()
        r.add_argument('name', type=str, required=True, help='No name provided',
                       location='json')
        r.add_argument('balance', type=int, default=0, location='json')
        args = r.parse_args()

        user = users.get_current_user().user_id()
        name, balance = args['name'], args['balance']

        acc = NDBAccount(user=user, name=name)
        accKey = acc.put()

        t = NDBTransaction()
        t.user          = user
        t.date          = datetime.date.today()
        t.amount        = balance
        t.account       = accKey
        t.description   = "Initial balance"
        t.put()

        return acc.asDict(), 201, \
                         {'Location':api.url_for(Account, key=accKey.urlsafe())}

class TransactionList(restful.Resource):
    decorators = [authRequired]

    def get(self):
        r = reqparse.RequestParser()
        r.add_argument('account', type=str, required=False, location='args')
        args = r.parse_args()

        if args['account'] is None:
            return ListResource.get('transactions', NDBTransaction)

        user = users.get_current_user().user_id()
        query = NDBTransaction.query(NDBTransaction.user==user)

        accKey = args['account']
        try:
            acc = retrieveEntry(accKey, (NDBAccount,))
            query = query.filter(NDBTransaction.account==acc.key)
        except:
            return Message.ERR_NO_ENTITY

        transfers = query.fetch()
        return {'transactions': [t.asDict() for t in transfers]}

    def post(self):
        r = reqparse.RequestParser()
        r.add_argument('date',        type=str, required=True,  location='json')
        r.add_argument('amount',      type=int, required=True,  location='json')
        r.add_argument('payeer',      type=str, required=False, location='json')
        r.add_argument('account',     type=str, required=True,  location='json')
        r.add_argument('description', type=str, required=False, location='json')
        r.add_argument('pair',        type=str, required=False, location='json')
        r.add_argument('category',    type=str, required=False, location='json')
        args = r.parse_args()

        t = NDBTransaction(user=users.get_current_user().user_id())

        # Parse required fields

        try:
            t.date = datetime.datetime.strptime(args['date'], "%Y-%m-%d").date()
            t.amount = args['amount']
            t.account = retrieveEntry(args['account'], (NDBAccount,)).key
        except:
            return Message.ERR_MALFORMED

        # Parse string optional fields

        t.payeer = args['payeer']
        t.description = args['description']

        # Parese key optional fields

        if args['pair'] is not None:
            try:
                t.pair = retrieveEntry(args['pair'], (NDBTransaction,)).key
            except:
                return Message.ERR_MALFORMED

        if args['category'] is not None:
            try:
                t.category = retrieveEntry(args['category'],
                                           (NDBCategory,NDBSubcategory)).key
            except:
                return Message.ERR_MALFORMED

        # Store changes

        tKey = t.put()
        return t.asDict(), 201, \
                      {'Location':api.url_for(Transaction, key=tKey.urlsafe())}

api.add_resource(AccountList,       '/api/accounts')
api.add_resource(Account,           '/api/account/<string:key>')
api.add_resource(TransactionList,   '/api/transactions')
api.add_resource(Transaction,       '/api/transaction/<string:key>')

def login_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not users.get_current_user():
            return flask.redirect(flask.url_for('index'))
        return func(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    afterLoginUrl = flask.url_for('dashboard')

    if users.get_current_user():
        return flask.redirect(afterLoginUrl)

    loginUrl = users.create_login_url(afterLoginUrl)
    return flask.render_template("index.html", loginUrl=loginUrl)

@app.route('/dashboard')
@login_required
def dashboard():
    user = users.get_current_user()
    logoutUrl = users.create_logout_url(flask.url_for('index'))
    accounts = NDBAccount.query().fetch()
    return flask.render_template("dashboard.html", user = user, \
                                                   logoutUrl = logoutUrl, \
                                                   accounts = accounts)
