Changelog
=========

Parsl 0.3.1
-----------

This is a point release with mostly minor features and several bug fixes

* Fixes for remote side handling
* Support for specifying IPythonDir for IPP controllers
* Several tests added that test provider launcher functionality from libsubmit
* This upgrade will also push the libsubmit requirement from 0.2.4 -> 0.2.5.


Several critical fixes from libsubmit are brought in :

* Several fixes and improvements to Condor from @annawoodard.
* Support for Torque scheduler
* Provider script output paths are fixed
* Increased walltimes to deal with slow scheduler system
* Srun launcher for slurm systems
* SSH channels now support file_pull() method
   While files are not automatically staged, the channels provide support for bi-directional file transport.

Parsl 0.3.0
-----------

Here are the major changes that are included in the Parsl 0.3.0 release.


New functionality
^^^^^^^^^^^^^^^^^

* Arguments to DFK has changed ::

    # Old
    dfk(executor_obj)

    # New, pass a list of executors
    dfk(executors=[list_of_executors])

    # Alternatively, pass the config from which the DFK will
    #instantiate resources
    dfk(config=config_dict)

* Execution providers have been restructured to a separate repo: `libsubmit <https://github.com/Parsl/libsubmit>`_

* Bash app styles have changes to return the commandline string rather than be assigned to the special keyword `cmd_line`.
  Please refer to `RFC #37 <https://github.com/Parsl/parsl/issues/37>`_ for more details. This is a **non-backward** compatible change.

* Output files from apps are now made available as an attribute of the AppFuture.
  Please refer `#26 <Output files from apps #26>`_ for more details. This is a **non-backward** compatible change ::

    # This is the pre 0.3.0 style
    app_fu, [file1, file2] = make_files(x, y, outputs=['f1.txt', 'f2.txt'])

    #This is the style that will be followed going forward.
    app_fu = make_files(x, y, outputs=['f1.txt', 'f2.txt'])
    [file1, file2] = app_fu.outputs

* DFK init now supports auto-start of IPP controllers

* Support for channels via libsubmit. Channels enable execution of commands from execution providers either
  locally, or remotely via ssh.

* Bash apps now support timeouts.

* Support for cobalt execution provider.


Bug fixes
^^^^^^^^^
* Futures have inconsistent behavior in bash app fn body `#35 <https://github.com/Parsl/parsl/issues/35>`_
* Parsl dflow structure missing dependency information `#30 <https://github.com/Parsl/parsl/issues/30>`_


Parsl 0.2.0
-----------

Here are the major changes that are included in the Parsl 0.2.0 release.

New functionality
^^^^^^^^^^^^^^^^^

* Support for execution via IPythonParallel executor enabling distributed execution.
* Generic executors

Parsl 0.1.0
-----------

Here are the major changes that are included in the Parsl 0.1.0 release.

New functionality
^^^^^^^^^^^^^^^^^

* Support for Bash and Python apps
* Support for chaining of apps via futures handled by the DataFlowKernel.
* Support for execution over threads.
* Arbitrary DAGs can be constructed and executed asynchronously.

Bug Fixes
^^^^^^^^^

* Initial release, no listed bugs.
