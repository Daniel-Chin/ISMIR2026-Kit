This directory contains extensions to help support the mini-conf library.

These include:

* `embeddings.py` : For turning abstracts into embeddings. Creates an `embeddings.torch` file. 

```bash
python embeddings.py ../sitedata/papers.csv embeddings.torch
```

* `reduce.py` : For creating two-dimensional representations of the embeddings.

```bash
python reduce.py ../sitedata/papers.csv embeddings.torch > ../sitedata/papers_projection.json
```

* `calendar_csv2ics.py`: converts events CSV to the downloadable ICS calendar. See [README_Schedule.md](README_Schedule.md).

* Image-Extraction: https://github.com/Mini-Conf/image-extraction for pulling images from PDF files. 

