import falcon
import logging
import os
from six.moves.urllib_parse import urljoin
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from traitlets.config.application import Application
from traitlets import Int, Instance, List, Tuple, Unicode, Bool, validate, TraitError
from uuid import uuid4

# falcon api
from ..server.api import FalconAPI

# deployer
from ..server.deploy import FalconDeploy

# base configs
from .user import User
from .notebook import Notebook
from .job import Job
from .report import Report

# base classes
from ..storage import UserStorage, NotebookStorage, JobStorage, ReportStorage

# dummy
from ..scheduler import DummyScheduler

# no auth
from ..middleware import NoUserMiddleware, NoAuthRequiredMiddleware

# essential middleware
from ..middleware import CORSMiddleware, MultipartMiddleware

# sql
from ..storage.sqla import Base
from ..storage.sqla import UserSQLStorage, NotebookSQLStorage, JobSQLStorage, ReportSQLStorage
from ..middleware import SQLAlchemySessionMiddleware, SQLUserMiddleware, SQLAuthRequiredMiddleware


class Paperboy(Application):
    """Base class for paperboy applications"""
    name = 'paperboy'
    description = 'paperboy'

    ############
    # Gunicorn #
    ############
    workers = Int(default_value=1, help="Number of gunicorn workers").tag(config=True)
    port = Unicode(default_value='8080', help="Port to run on").tag(config=True)
    ############

    ##########
    # Falcon #
    ##########
    api = Instance(falcon.API, help="A Falcon API instance").tag(config=True)
    ##########

    ########
    # URLs #
    ########
    baseurl = Unicode(default_value='/', help="Base URL (for reverse proxies)").tag(config=True)
    apiurl = Unicode(default_value='/api/v1/', help="API base URL (for reverse proxies)").tag(config=True)
    loginurl = Unicode(default_value='login', help="login url").tag(config=True)
    logouturl = Unicode(default_value='logout', help="logout url").tag(config=True)
    registerurl = Unicode(default_value='register', help="register url").tag(config=True)
    ########

    #############
    # Misc Auth #
    #############
    http = Bool(default_value=True, help="Running on HTTP (as opposed to https, so token is insecure)").tag(config=True)
    include_password = Bool(default_value=False).tag(config=True)
    include_register = Bool(default_value=True).tag(config=True)
    token_timeout = Int(default_value=600).tag(config=True)
    #############

    def _login_redirect(config, *args, **kwargs):
        raise falcon.HTTPFound(urljoin(config.baseurl, config.loginurl))

    ################################################
    # FIXME doesnt allow default_value yet         #
    user_storage = UserSQLStorage
    user_config = User
    notebook_storage = NotebookSQLStorage
    notebook_config = Notebook
    job_storage = JobSQLStorage
    job_config = Job
    report_storage = ReportSQLStorage
    report_config = Report
    #                                              #
    scheduler = DummyScheduler
    #                                              #
    auth_required_mw = Instance(object)
    load_user_mw = Instance(object)
    # END                                          #
    ################################################

    ##############
    # Middleware #
    ##############
    essential_middleware = [CORSMiddleware(allow_all_origins=True).middleware,
                            MultipartMiddleware()]
    extra_middleware = List(default_value=[])  # List of extra middlewares to install
    ##############

    ##################
    # Custom handler #
    ##################
    extra_handlers = List(trait=Tuple(), default_value=[])  # List of tuples (route, handler) of handlers to install
    ##################

    ##########################################
    #        Predefined Configurations       #
    #
    ##########################################
    backend = Unicode(default_value='dummy', help="Backend set to use, options are {sqla, custom}").tag(config=True)
    auth = Unicode(default_value='dummy', help="Authentication backend set to use, options are {none, sqla, custom}").tag(config=True)
    secret = Unicode()

    @validate('backend')
    def _validate_backend(self, proposed):
        if proposed['value'] not in ('custom', 'dummy', 'git', 'sqla',):
            raise TraitError('backend not recognized: %s'.format(proposed['value']))
        return proposed['value']

    @validate('auth')
    def _validate_auth(self, proposed):
        if proposed['value'] not in ('custom', 'none', 'sqla',):
            raise TraitError('backend not recognized: %s'.format(proposed['value']))
        return proposed['value']
    ##########################################

    ##############
    # SQL extras #
    ##############
    sql_url = Unicode(default_value='sqlite:///paperboy.db', help="SQL Alchemy url").tag(config=True)
    engine = None
    sessionmaker = None
    sql_user = Bool(default_value=True)
    sql_dev = Bool(default_value=False)
    ##############

    ##################
    # Airflow extras #
    ##################
    airflow_dagbag = Unicode(default_value=os.path.expanduser('~/airflow/dags'))
    ##################

    ##################
    # Output #
    ##################
    output_type = Unicode(default_value='directory')
    output_dir = Unicode(default_value=os.path.expanduser('~/Downloads'))
    ##################

    def start(self):
        """Start the whole thing"""
        self.port = os.environ.get('PORT', self.port)
        options = {
            'bind': '0.0.0.0:{}'.format(self.port),
            'workers': self.workers
        }
        self.secret = str(uuid4())

        if self.sql_dev:

            self.sql_url = 'sqlite:///:memory:'
            logging.critical('Using SQL in memory backend')

            self.engine = create_engine(self.sql_url, echo=False)
            Base.metadata.create_all(self.engine)

            self.sessionmaker = sessionmaker(bind=self.engine)
            self.backend = 'sqla'
            self.auth = 'sqla'
            self.extra_middleware = self.extra_middleware + [SQLAlchemySessionMiddleware(self.sessionmaker)]
            self.notebook_storage = NotebookSQLStorage
            self.job_storage = JobSQLStorage
            self.report_storage = ReportSQLStorage
            self.user_storage = UserSQLStorage
            self.sql_user = True

            logging.critical('Using SQL auth')
            self.auth_required_mw = SQLAuthRequiredMiddleware
            self.load_user_mw = SQLUserMiddleware

        else:
            # Preconfigured storage backends
            if self.backend == 'git':
                logging.critical('Using Git backend')
                raise NotImplemented

            elif self.backend == 'sqla':
                logging.critical('Using SQL backend')

                self.engine = create_engine(self.sql_url, echo=False)
                Base.metadata.create_all(self.engine)

                self.sessionmaker = sessionmaker(bind=self.engine)
                self.extra_middleware = self.extra_middleware + [SQLAlchemySessionMiddleware(self.sessionmaker)]
                self.notebook_storage = NotebookSQLStorage
                self.job_storage = JobSQLStorage
                self.report_storage = ReportSQLStorage
                self.user_storage = UserSQLStorage
                self.sql_user = True
                self.auth = 'sqla'

            # Preconfigured auth backends
            if self.auth == 'none':
                logging.critical('Using No auth')
                self.auth_required_mw = NoAuthRequiredMiddleware
                self.load_user_mw = NoUserMiddleware

            elif self.auth == 'sqla':
                logging.critical('Using SQL auth')
                self.auth_required_mw = SQLAuthRequiredMiddleware
                self.load_user_mw = SQLUserMiddleware

        FalconDeploy(FalconAPI(self), options).run()

    @classmethod
    def launch_instance(cls, argv=None, **kwargs):
        """Launch an instance of a Paperboy Application"""
        return super(Paperboy, cls).launch_instance(argv=argv, **kwargs)

    def to_dict(self):
        return {'name': self.name,
                'description': self.description,
                'workers': self.workers,
                'port': self.port}
    aliases = {
        'workers': 'Paperboy.workers',
        'port': 'Paperboy.port',
        'baseurl': 'Paperboy.baseurl',
        'backend': 'Paperboy.backend',
        'auth': 'Paperboy.auth',
        'sql_url': 'Paperboy.sql_url',
    }
