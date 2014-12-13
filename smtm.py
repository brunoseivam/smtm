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
    NO_CONTENT          = None, 204

class NDBPlace(ndb.Model):
    name        = ndb.StringProperty(required=True)
    icon        = ndb.StringProperty()
    aliases     = ndb.StringProperty(repeated=True)

class NDBAccount(ndb.Model):
    user        = ndb.StringProperty(required=True)
    name        = ndb.StringProperty(required=True)

    def asDict(self):
        return {'name': self.name}

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

def authRequired(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not users.get_current_user():
            return Message.ERR_NOT_AUTH
        return func(*args, **kwargs)
    return decorated

class AccountList(restful.Resource):
    decorators = [authRequired]

    def get(self):
        user = users.get_current_user().user_id()
        accounts = NDBAccount.query(NDBAccount.user==user).fetch()
        return {'accounts': [acc.name for acc in accounts]}

    def post(self):
        r = reqparse.RequestParser()
        r.add_argument('name', type=str, required=True, help='No name provided',
                       location='json')
        r.add_argument('balance', type=int, default=0, location='json')

        args = r.parse_args()
        user = users.get_current_user().user_id()
        name, balance = args['name'], args['balance']

        q = NDBAccount.query(NDBAccount.user == user, NDBAccount.name == name)
        if q.get() is not None:
            return Message.ERR_ENTITY_EXISTS

        acc = NDBAccount(user=user, name=name)
        accKey = acc.put()

        t = NDBTransaction()
        t.user          = user
        t.date          = datetime.date.today()
        t.amount        = balance
        t.account       = accKey
        t.description   = "Initial balance"
        t.put()

        return acc.asDict(), 201, {'Location':api.url_for(Account, name=name)}


class Account(restful.Resource):
    decorators = [authRequired]

    @staticmethod
    def retrieve(name):
        user = users.get_current_user().user_id()
        q = NDBAccount.query(NDBAccount.user==user,NDBAccount.name==name)
        return q.get()

    def get(self, name):
        acc = Account.retrieve(name)
        return acc.asDict() if acc is not None else Message.ERR_NO_ENTITY

    def put(self, name):
        r = reqparse.RequestParser()
        r.add_argument('name', type=str, required=True, help='No name provided',
                       location='json')
        args = r.parse_args()

        newName = args['name']

        acc = Account.retrieve(name)
        if acc is None:
            return Message.ERR_NO_ENTITY

        if Account.retrieve(newName) is not None:
            return Message.ERR_CONFLICT

        acc.name = newName
        acc.key.put()
        return acc.asDict(), 200

    def delete(self, name):
        acc = Account.retrieve(name)

        if acc is None:
            return Message.ERR_NO_ENTITY

        acc.key.delete()
        return Message.NO_CONTENT

class TransactionList(restful.Resource):
    decorators = [authRequired]

    def get(self):
        pass

class Transaction(restful.Resource):
    pass


api.add_resource(AccountList, '/api/accounts')
api.add_resource(Account, '/api/account/<string:name>')
api.add_resource(TransactionList, 'api.transactions')


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
