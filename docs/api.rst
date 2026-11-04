API reference
=============

The public, versioned API is re-exported from the top-level package. Downstream
tools depend only on the symbols documented here; their stability is governed by
SemVer (see ``AGENTS.md``).

.. automodule:: asf_downloader
   :members: __version__

.. automodule:: asf_downloader.catalog
   :members:

.. automodule:: asf_downloader.transfer
   :no-members:

.. autodata:: asf_downloader.transfer.BACKENDS

.. autofunction:: asf_downloader.transfer.get_backend

.. autoclass:: asf_downloader.transfer.UnknownBackendError

.. automodule:: asf_downloader.transfer.base
   :members:

.. automodule:: asf_downloader.transfer.https
   :members:

.. automodule:: asf_downloader.config
   :members:

.. automodule:: asf_downloader.cli
   :members:

.. automodule:: asf_downloader.nisar_archive
   :members:

.. automodule:: asf_downloader.utils
   :members:

.. automodule:: asf_downloader.profiles
   :members:

.. automodule:: asf_downloader.profiles.base
   :members:

.. automodule:: asf_downloader.profiles.nisar
   :members:
