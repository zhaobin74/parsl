'''
DataFlowKernel
==============

The DataFlowKernel adds dependency awareness to an existing executor.
It is responsible for managing futures, such that when dependencies are resolved,
pending tasks move to the runnable state.

Here's a simplified diagram of what happens internally::

    User             |        DFK         |    Executor
    ----------------------------------------------------------
                     |                    |
          Task-------+> +Submit           |
        App_Fu<------+--|                 |
                     |  Dependencies met  |
                     |         task-------+--> +Submit
                     |        Ex_Fu<------+----|
'''

import copy
import uuid
import logging
import atexit
import signal
import random
from inspect import signature
from concurrent.futures import Future
from functools import partial

from parsl.dataflow.error import *
from parsl.dataflow.states import States
from parsl.dataflow.futures import AppFuture
from parsl.dataflow.rundirs import make_rundir
from parsl.dataflow.flow_control import FlowControl, FlowNoControl
from parsl.dataflow.usage_tracking.usage import UsageTracker
from parsl.dataflow.config_defaults import update_config
from parsl.app.futures import DataFuture
from parsl.execution_provider.provider_factory import ExecProviderFactory as EPF

#from parsl.dataflow.start_controller import Controller
# Exceptions

logger = logging.getLogger(__name__)

class DataFlowKernel(object):
    """ DataFlowKernel
    """

    def __init__(self, config=None, executors=None, lazy_fail=True,
                 rundir=None, fail_retries=2):
        """ Initialize the DataFlowKernel

        Please note that keyword args passed to the DFK here will always override
        options passed in via the config.

        KWargs:
            config (Dict) : A single data object encapsulating all config attributes
            executors (list of Executor objs): Optional, kept for (somewhat) backward compatibility with 0.2.0
            lazy_fail(Bool) : Default=True, determine failure behavior
            rundir (str) : Path to run directory. Defaults to ./runinfo/runNNN
            fail_retries(int): Default=2, Set the number of retry attempts in case of failure

        Returns:
            DataFlowKernel object
        """
        # Create run dirs for this run
        self.rundir = make_rundir(config=config, path=rundir)

        # Update config with defaults
        self._config = update_config(config, self.rundir)

        # Start the anonymized usage tracker and send init msg
        self.usage_tracker = UsageTracker(self)
        self.usage_tracker.send_message()

        if self._config :
            self._executors_managed = True
            # Create the executors
            epf = EPF()
            self.executors = epf.make(self.rundir, self._config)

            # set global vars from config
            self.lazy_fail = self._config["globals"].get("lazyFail", lazy_fail)
            self.fail_retries = self._config["globals"].get("fail_retries", fail_retries)
            self.flowcontrol     = FlowControl(self, self._config)
        else:
            self._executors_managed = False
            self.fail_retries = fail_retries
            self.lazy_fail    = lazy_fail
            self.executors    = {i:x for i,x in enumerate(executors)}
            print("Executors : ", self.executors)
            self.flowcontrol  = FlowNoControl(self, None)

        self.task_count      = 0
        self.fut_task_lookup = {}
        self.tasks           = {}


        logger.debug("Using executors: {0}".format(self.executors))
        atexit.register(self.cleanup)

    @staticmethod
    def _count_deps(depends, task_id):
        ''' Internal. Count the number of unresolved futures in the list depends'''

        count = 0
        for dep in depends:
            if isinstance(dep, Future) or issubclass(type(dep), Future):
                logger.debug("Task[%s]: dep:%s done:%s", task_id, dep, dep.done())
                if not dep.done():
                    count += 1

        return count

    @property
    def config(self):
        ''' Returns the fully initialized config that the DFK is
        actively using. DO *NOT* update.
        Returns:
             - config (dict)
        '''

        return self._config

    def handle_update(self, task_id, future):
        ''' This function is called only as a callback from a task being done
        Move done task from runnable -> done
        Move newly doable tasks from pending -> runnable , and launch

        Args:
             task_id (string) : Task id which is a uuid string
             future (Future) : The future object corresponding to the task which makes this callback
        '''
        if future.done():

            # Untested
            if not self.lazy_fail:
                # Fail early
                try:
                    future.result()
                except Exception as e:
                    logger.warn("Exception : %s", future._exception)
                    logger.error("Task[%s]: FAILED with %s", task_id, future)
                    self.tasks[task_id]['status'] = States.failed
                    raise e

            logger.debug("Task[%s]: COMPLETED with %s", task_id, future)
            self.tasks[task_id]['status'] = States.done

        # Identify tasks that have resolved dependencies and launch
        for tid in list(self.tasks):
            # Skip all non-pending tasks
            if self.tasks[tid]['status'] != States.pending:
                continue

            if self._count_deps(self.tasks[tid]['depends'], tid) == 0:
                # We can now launch *task*
                new_args, kwargs, exceptions = self.sanitize_and_wrap(task_id,
                                                                      self.tasks[tid]['args'],
                                                                      self.tasks[tid]['kwargs'])

                if not exceptions :
                    logger.debug("Task[%s] Launching Task".format(tid))
                    # There are no dependency errors
                    self.tasks[tid]['status'] = States.running
                    exec_fu = self.launch_task(tid, self.tasks[tid]['func'], *new_args, **kwargs)
                    self.tasks[task_id]['exec_fu'] = exec_fu
                    try:
                        self.tasks[tid]['app_fu'].update_parent(exec_fu)
                        self.tasks[tid]['exec_fu'] = exec_fu
                    except AttributeError as e:
                        logger.error("Task[%s]: Caught AttributeError at update_parent", tid)
                        raise e
                else:
                    logger.debug("Task[%s]: Deferring Task due to dependency failure", tid)
                    # Raise a dependency exception
                    self.tasks[tid]['status'] = States.dep_fail
                    try:
                        fu = Future()
                        self.tasks[tid]['exec_fu'] = fu
                        self.tasks[tid]['app_fu'].update_parent(fu)
                        fu.set_exception(DependencyError(exceptions,
                                                         tid,
                                                         None))
                        print(self.tasks[tid]['app_fu'])

                    except AttributeError as e:
                        logger.error("Task[%s]: Caught AttributeError at update_parent", tid)
                        raise e

        return


    def write_status_log(self):
        ''' Write status log.

        Args:
           None

        Kwargs:
           None
        '''

        state_lens = {States.unsched : 0,
                      States.pending : 0,
                      States.runnable: 0,
                      States.running : 0,
                      States.done    : 0,
                      States.failed  : 0,
                      States.dep_fail: 0}

        for tid in self.tasks:
            state_lens[self.tasks[tid]['status']] += 1

        logger.debug("Pending:%d   Runnable:%d   Done:%d", state_lens[States.pending],
                     state_lens[States.runnable],
                     state_lens[States.done])


    def print_status_log(self):
        ''' Print status log in terms of pending, runnable and done tasks

        Args:
           None

        Kwargs:
           None
        '''

        state_lens = {States.unsched : 0,
                      States.pending : 0,
                      States.runnable: 0,
                      States.running : 0,
                      States.done    : 0,
                      States.failed  : 0,
                      States.dep_fail: 0}

        for tid in self.tasks:
            state_lens[self.tasks[tid]['status']] += 1

        print("Pending:{0}   Runnable:{1}   Done:{2}".format( state_lens[States.pending],
                                                              state_lens[States.runnable],
                                                              state_lens[States.done] ))

    def launch_task(self, task_id, executable, *args, **kwargs):
        ''' Handle the actual submission of the task to the executor layer

        If the app task has the sites attributes not set (default=='all')
        the task is launched on a randomly selected executor from the
        list of executors. This behavior could later be updates to support
        binding to sites based on user specified criteria.

        If the app task specifies a particular set of sites, it will be
        targetted at those specific sites.

        Args:
            task_id (uuid string) : A uuid string that uniquely identifies the task
            executable (callable) : A callable object
            args (list of positional args)
            kwargs (list of keyword args)


        Returns:
            Future that tracks the execution of the submitted executable
        '''

        task_name    = executable.__name__
        target_sites = self.tasks[task_id]["sites"]
        executor     = None
        if isinstance(target_sites, str) and target_sites.lower() == 'all' :
            # Pick a random site from the list
            site, executor = random.choice(list(self.executors.items()))

        elif isinstance(target_sites, list) :
            # Pick a random site from user specified list
            try :
                site = random.choice(target_sites)
                executor = self.executors[site]

            except Exception as e:
                logger.error("Task[%s]: requests invalid site [%s]" % task_id, target_sites)
        else:
            logger.error("App[%s]: sites defined is invalid, neither str|list" % self.tasks[task_id]['func'].__name__)

        exec_fu = executor.submit(executable, *args, **kwargs)
        exec_fu.add_done_callback(partial(self.handle_update, task_id))
        logger.debug("Task[%s] launched on executor:%s" %(task_id, executor))
        return exec_fu

    @staticmethod
    def _count_all_deps(task_id, args, kwargs):
        ''' Internal. Count the number of unresolved futures in the list depends
        Args:
            task_id (uuid string) : Task_id
            args (List[args]) : The list of args list to the fn
            kwargs (Dict{kwargs}) : The dict of all kwargs passed to the fn

        Returns:
            count, [list of dependencies]

        '''

        # Check the positional args
        depends = []
        count   = 0
        for dep in args :
            if isinstance(dep, Future) or issubclass(dep.__class__, Future):
                if not dep.done():
                    count += 1
                depends.extend([dep])

        # Check for explicit kwargs ex, fu_1=<fut>
        for key in kwargs:
            dep = kwargs[key]
            if isinstance(dep, Future) or issubclass(dep.__class__, Future):
                if not dep.done():
                    count += 1
                depends.extend([dep])

        # Check for futures in inputs=[<fut>...]
        for dep in kwargs.get('inputs', []):
            if issubclass(dep.__class__, Future) or isinstance(dep, Future):
                if not dep.done():
                    count += 1
                depends.extend([dep])

        #logger.debug("Task:{0}   dep_cnt:{1}  deps:{2}".format(task_id, count, depends))
        return count, depends

    @staticmethod
    def sanitize_and_wrap(task_id, args, kwargs):
        ''' This function should be called **ONLY** when all the futures we track
        have been resolved. If the user hid futures a level below, we will not catch
        it, and will (most likely) result in a type error .

        Args:
             task_id (uuid str) : Task id
             func (Function) : App function
             args (List) : Positional args to app function
             kwargs (Dict) : Kwargs to app function

        Return:
             partial Function evaluated with all dependencies in  args, kwargs and kwargs['inputs'] evaluated.

        '''

        dep_failures = []

        # Replace item in args
        new_args = []
        for dep in args :
            if isinstance(dep, Future) or issubclass(type(dep), Future):
                try :
                    new_args.extend([dep.result()])
                except Exception as e:
                    dep_failures.extend([e])
            else:
                new_args.extend([dep])

        # Check for explicit kwargs ex, fu_1=<fut>
        for key in kwargs:
            dep = kwargs[key]
            if isinstance(dep, Future) or issubclass(type(dep), Future):
                try :
                    kwargs[key] = dep.result()
                except Exception as e:
                    dep_failures.extend([e])

        # Check for futures in inputs=[<fut>...]
        if 'inputs' in kwargs:
            new_inputs = []
            for dep in kwargs['inputs']:
                if isinstance(dep, Future) or issubclass(type(dep), Future):
                    try :
                        new_inputs.extend([dep.result()])
                    except Exception as e:
                        dep_failures.extend([e])

                else:
                    new_inputs.extend([dep])
            kwargs['inputs'] = new_inputs

        return new_args, kwargs, dep_failures


    def submit (self, func, *args, parsl_sites='all', **kwargs):
        ''' Add task to the dataflow system.

        Args:
             func : A function object
             *args : Args to the function

        KWargs :
             Standard kwargs to the func as provided by the user
             parsl_sites : List of sites as defined in the config, Default :'all'
             This is the only kwarg that is passed in by the app definition.

        If all deps are met :
              send to the runnable queue
              and launch the task
        Else:
              post the task in the pending queue

        Returns:
               (AppFuture) [DataFutures,]
        '''

        task_id = self.task_count
        self.task_count += 1

        # Get the dep count and a list of dependencies for the task
        dep_cnt, depends = self._count_all_deps(task_id, args, kwargs)

        task_def = { 'depends'    : depends,
                     'sites'      : parsl_sites,
                     'func'       : func,
                     'func_name'  : func.__name__,
                     'args'       : args,
                     'kwargs'     : kwargs,
                     'callback'   : None,
                     'dep_cnt'    : dep_cnt,
                     'exec_fu'    : None,
                     'status'     : States.unsched,
                     'app_fu'     : None  }

        if task_id in self.tasks:
            raise DuplicateTaskError("Task {0} in pending list".format(task_id))
        else:
            self.tasks[task_id] = task_def

        # Extract stdout and stderr to pass to AppFuture:
        task_stdout = kwargs.get('stdout', None)
        task_stderr = kwargs.get('stderr', None)

        if dep_cnt == 0 :
            # Set to running
            new_args, kwargs, exceptions = self.sanitize_and_wrap(task_id, args, kwargs)
            if not exceptions:
                self.tasks[task_id]['exec_fu'] = self.launch_task(task_id, func, *new_args, **kwargs)
                self.tasks[task_id]['app_fu']  = AppFuture(self.tasks[task_id]['exec_fu'],
                                                           tid=task_id,
                                                           stdout=task_stdout,
                                                           stderr=task_stderr)
                self.tasks[task_id]['status']  = States.running
            else:
                self.tasks[task_id]['exec_fu'] = None
                app_fu = AppFuture(self.tasks[task_id]['exec_fu'],
                                   tid=task_id,
                                   stdout=task_stdout,
                                   stderr=task_stderr)
                app_fu.set_exception(DependencyError(exceptions,
                                                     "Failures in input dependencies",
                                                     None))
                self.tasks[task_id]['app_fu']  = app_fu
                self.tasks[task_id]['status']  = States.dep_fail
        else:
            # Send to pending, create the AppFuture with no parent and have it set
            # when an executor future is available.
            self.tasks[task_id]['app_fu']  = AppFuture(None, tid=task_id,
                                                       stdout=task_stdout,
                                                       stderr=task_stderr)
            self.tasks[task_id]['status']  = States.pending

        logger.debug("Task:%s Launched with AppFut:%s", task_id, task_def['app_fu'])
        return task_def['app_fu']


    def cleanup (self):
        '''  DataFlowKernel cleanup. This involves killing resources explicitly and
        sending die messages to IPP workers.

        If the executors are managed, i.e created by the DFK
            then : we scale_in each of the executors and call executor.shutdown
            else : we do nothing. Executor cleanup is left to the user.

        '''

        logger.debug("DFK cleanup initiated")

        # Send final stats
        self.usage_tracker.send_message()
        # We do not need to cleanup if the executors are managed outside
        # the DFK
        if not self._executors_managed :
            return

        for executor in self.executors.values() :
            if executor.scaling_enabled :
                job_ids = executor.execution_provider.resources.keys()
                executor.scale_in(len(job_ids))

            # We are not doing shutdown here because even with block=False this blocks.
            executor.shutdown()

        logger.debug("DFK cleanup complete")
