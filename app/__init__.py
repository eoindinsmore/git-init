"""Streamlit dashboard package.

Charter layering contract: this package contains **zero** analytics. It reads the
point-in-time store (``quant.store``) and the registry (``registry.loader``), and
calls ``quant.transforms`` for any growth/level/MA view. All maths lives in ``quant/``.
"""
