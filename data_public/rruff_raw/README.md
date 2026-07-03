# RRUFF Raman raw fixture

This directory contains a small offline RRUFF-style Raman text fixture set for LabFlow Agent compatibility validation.

The files are intentionally small and text-based so the converter can be tested without network access. They mimic the common structure of public RRUFF Raman exports: optional header/comment lines followed by numeric Raman shift and intensity pairs.

Users may replace or extend these files with locally downloaded public RRUFF Raman `.txt` spectra. The converted LabFlow batch is used to validate file compatibility, workflow traceability, and report generation only. It is not used to claim mineral identification accuracy or scientific interpretation quality.
