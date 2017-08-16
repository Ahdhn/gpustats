#!/usr/bin/env python

import pandas as pd
import numpy as np
import requests
import re
import os
import json

from altair import *

from fileops import save

data = {
    'NVIDIA': {'url': 'https://en.wikipedia.org/wiki/List_of_Nvidia_graphics_processing_units',
               },
    'AMD': {'url': 'https://en.wikipedia.org/wiki/List_of_AMD_graphics_processing_units',
            }
}

for vendor in ['NVIDIA', 'AMD']:
    # requests.get handles https
    html = requests.get(data[vendor]['url']).text
    # oddly, some dates look like:
    # <td><span class="sortkey" style="display:none;speak:none">000000002010-02-25-0000</span><span style="white-space:nowrap">Feb 25, 2010</span></td>
    html = re.sub(
        r'<span [^>]*style="display:none[^>]*>([^<]+)</span>', '', html)
    html = re.sub(r'<span[^>]*>([^<]+)</span>', r'\1', html)
    with open('/tmp/%s.html' % vendor, 'w') as f:
        f.write(html.encode('utf8'))

    dfs = pd.read_html(html, match='Launch', parse_dates=True)
    for df in dfs:
        # Multi-index to index
        df.columns = [' '.join(col).strip() for col in df.columns.values]
        # Get rid of 'Unnamed' column names
        df.columns = [re.sub(' Unnamed: [0-9]+_level_[0-9]+', '', col)
                      for col in df.columns.values]

        # If a column-name word ends in a number or number,comma,number, delete
        # it
        df.columns = [' '.join([re.sub('[\d,]+$', '', word) for word in col.split()])
                      for col in df.columns.values]
        # If a column-name word ends with one or more '[x]',
        # where 'x' is a lower-case letter or number, delete it
        df.columns = [' '.join([re.sub(r'(?:\[[a-z0-9]+\])+$', '', word) for word in col.split()])
                      for col in df.columns.values]
        df['Vendor'] = vendor
        df['Launch'] = df['Launch'].apply(
            lambda x: pd.to_datetime(x,
                                     infer_datetime_format=True,
                                     errors='coerce'))

    data[vendor]['dfs'] = dfs

df = pd.concat(data['NVIDIA']['dfs'] + data['AMD']['dfs'], ignore_index=True)


def merge(df, dst, src, replaceNoWithNaN=False):
    if replaceNoWithNaN:
        df[src] = df[src].replace('No', np.nan)
    df[dst] = df[dst].fillna(df[src])
    df.drop(src, axis=1, inplace=True)
    return df

# merge related columns
df = merge(df, 'Model', 'Model Units')
df = merge(df, 'SM count', 'SMM count')
df = merge(df, 'SM count', 'SMX count')
df = merge(df, 'Processing power (GFLOPS) Single precision',
           'Processing power (GFLOPS)')
df = merge(df, 'Processing power (GFLOPS) Single precision',
           'Processing power (GFLOPS) Single')
df = merge(df, 'Processing power (GFLOPS) Single precision',
           'Processing power (GFLOPS) Single precision (MAD+MUL)',
           replaceNoWithNaN=True)
df = merge(df, 'Processing power (GFLOPS) Single precision',
           'Processing power (GFLOPS) Single precision (MAD or FMA)',
           replaceNoWithNaN=True)
df = merge(df, 'Processing power (GFLOPS) Double precision',
           'Processing power (GFLOPS) Double')
df = merge(df, 'Processing power (GFLOPS) Double precision',
           'Processing power (GFLOPS) Double precision (FMA)',
           replaceNoWithNaN=True)
df = merge(df, 'Memory Bandwidth (GB/s)',
           'Memory configuration Bandwidth (GB/s)')
df = merge(df, 'TDP (Watts)', 'TDP (Watts) GPU only')
df = merge(df, 'TDP (Watts)', 'TDP (Watts) (GPU only)')
df = merge(df, 'TDP (Watts)', 'TDP (Watts) Max.')
df = merge(df, 'TDP (Watts)', 'TDP (Watts) W')
df = merge(df, 'Model', 'Model (Codename)')
df = merge(df, 'Model', 'Model: Mobility Radeon')

# filter out {Chips, Code name, Core config}: '^[2-9]\u00d7'
df[df['Chips'].str.contains(u'^[2-9]\u00d7') == False]
df[df['Code name'].str.contains(u'^[2-9]\u00d7') == False]
df[df['Core config'].str.contains(u'^[2-9]\u00d7') == False]
# filter out if Model ends in [xX]2
df[df['Model'].str.contains('[xX]2$') == False]
# filter out transistors that ends in x2
df[df['Transistors (million)'].str.contains(u'\u00d7[2-9]$') == False]

# merge GFLOPS columns with "Boost" column headers and rename
for prec in ['Double', 'Single', 'Half']:
    # the next three pick the base clock from base (boost)
    tomerge = 'Processing power (GFLOPS) %s precision (Boost)' % prec
    df['Processing power (GFLOPS) %s precision' % prec] = df['Processing power (GFLOPS) %s precision' % prec].fillna(
        df[tomerge].str.split(' ').str[0])
    df.drop(tomerge, axis=1, inplace=True)

    tomerge = 'Processing power (GFLOPS) %s (Boost)' % prec
    df['Processing power (GFLOPS) %s precision' % prec] = df['Processing power (GFLOPS) %s precision' % prec].fillna(
        df[tomerge].str.split(' ').str[0])
    df.drop(tomerge, axis=1, inplace=True)

    if prec == 'Single':
        tomerge = 'Processing power (GFLOPS) (Boost)'
        df['Processing power (GFLOPS) %s precision' % prec] = df['Processing power (GFLOPS) %s precision' % prec].fillna(
            df[tomerge].str.split(' ').str[0])
        df.drop(tomerge, axis=1, inplace=True)

    # convert TFLOPS to GFLOPS
    tomerge = 'Processing power (TFLOPS) %s (Boost)' % prec
    df['Processing power (GFLOPS) %s precision' % prec] = df['Processing power (GFLOPS) %s precision' % prec].fillna(
        pd.to_numeric(df[tomerge].str.split(' ').str[0], errors='coerce') * 1000.0)
    df.drop(tomerge, axis=1, inplace=True)

    df = df.rename(columns={'Processing power (GFLOPS) %s precision' % prec:
                            '%s-precision GFLOPS' % prec})

# split out 'transistors die size'
# example: u'292\u00d7106 59 mm2'
for exponent in [u'\u00d7106', u'\u00d7109', 'B']:
    dftds = df['Transistors Die Size'].str.extract(u'^([\d\.]+)%s (\d+) mm2' % exponent,
                                                   expand=True)
    if exponent == u'\u00d7106':
        df['Transistors (million)'] = df['Transistors (million)'].fillna(
            pd.to_numeric(dftds[0], errors='coerce'))
    if exponent == u'\u00d7109' or exponent == 'B':
        df['Transistors (billion)'] = df['Transistors (billion)'].fillna(
            pd.to_numeric(dftds[0], errors='coerce'))
    df['Die size (mm2)'] = df['Die size (mm2)'].fillna(
        pd.to_numeric(dftds[1], errors='coerce'))


# merge transistor counts
df['Transistors (billion)'] = df['Transistors (billion)'].fillna(
    pd.to_numeric(df['Transistors (million)'], errors='coerce') / 1000.0)

# extract shader (processor) counts
df['Pixel/unified shader count'] = df['Core config'].str.split(':').str[0]
df = merge(df, 'Pixel/unified shader count', 'Stream processors')
df = merge(df, 'Pixel/unified shader count', 'Shaders Cuda cores (total)')

for col in ['Memory Bandwidth (GB/s)', 'TDP (Watts)']:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# compute arithmetic intensity and FLOPS/Watt
df['Arithmetic intensity (FLOP/B)'] = pd.to_numeric(df[
    'Single-precision GFLOPS'], errors='coerce') / pd.to_numeric(df['Memory Bandwidth (GB/s)'], errors='coerce')
df['FLOPS/Watt'] = pd.to_numeric(df[
    'Single-precision GFLOPS'], errors='coerce') / pd.to_numeric(df['TDP (Watts)'], errors='coerce')

# remove references from end of model names
df['Model'] = df['Model'].str.replace(r'(?:\s*\[\d+\])+(?:\d+,)?(?:\d+)?$', '')

# mark mobile processors
df['GPU Type'] = np.where(
    df['Model'].str.contains(r' [\d]+M[X]?|\(Notebook\)'), 'Mobile', 'Desktop')

# values=c("amd"="#ff0000",
#   "nvidia"="#76b900",
#   "intel"="#0860a8",

colormap = Scale(domain=['AMD', 'NVIDIA'],
                 range=['#ff0000', '#76b900'])

mb = Chart(df).mark_point().encode(
    x='Launch:T',
    y=Y('Memory Bandwidth (GB/s):Q',
        scale=Scale(type='log'),
        ),
    color=Color('Vendor',
                scale=colormap,
                ),
    shape='GPU Type',
)
pr = Chart(pd.melt(df,
                   id_vars=['Launch', 'Model', 'GPU Type', 'Vendor'],
                   value_vars=['Single-precision GFLOPS',
                               'Double-precision GFLOPS',
                               'Half-precision GFLOPS'],
                   var_name='Datatype',
                   value_name='Processing power (GFLOPS)')).mark_point().encode(
    x='Launch:T',
    y=Y('Processing power (GFLOPS):Q',
        scale=Scale(type='log'),
        ),
    shape='Datatype',
    color=Color('Vendor',
                scale=colormap,
                ),
)

sm = Chart(df).mark_point().encode(
    x='Launch:T',
    y='SM count:Q',
    color=Color('Vendor',
                scale=colormap,
                ),
)
die = Chart(df).mark_point().encode(
    x='Launch:T',
    y=Y('Die size (mm2):Q',
        scale=Scale(type='log'),
        ),
    color=Color('Vendor',
                scale=colormap,
                ),
)
xt = Chart(df).mark_point().encode(
    x='Launch:T',
    y=Y('Transistors (billion):Q',
        scale=Scale(type='log'),
        ),
    color=Color('Vendor',
                scale=colormap,
                ),
)
fab = Chart(df).mark_point().encode(
    x='Launch:T',
    y=Y('Fab (nm):Q',
        scale=Scale(type='log'),
        ),
    color=Color('Vendor',
                scale=colormap,
                ),
)
ai = Chart(df).mark_point().encode(
    x='Launch:T',
    y='Arithmetic intensity (FLOP/B):Q',
    shape='GPU Type',
    color=Color('Vendor',
                scale=colormap,
                ),
)

fpw = Chart(df).mark_point().encode(
    x='Launch:T',
    y='FLOPS/Watt:Q',
    shape='GPU Type',
    color=Color('Vendor',
                scale=colormap,
                ),
)

sh = Chart(df).mark_point().encode(
    x='Launch:T',
    y=Y('Pixel/unified shader count:Q',
        scale=Scale(type='log'),
        ),
    shape='GPU Type',
    color=Color('Vendor',
                scale=colormap,
                ),
)

df.to_csv("/tmp/gpu.csv", encoding="utf-8")

template = """<!DOCTYPE html>
<html>
<head>
  <!-- Import Vega 3 & Vega-Lite 2 js (does not have to be from cdn) -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/vega/3.0.0-rc7/vega.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/vega-lite/2.0.0-beta.11/vega-lite.js"></script>
  <!-- Import vega-embed -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/vega-embed/3.0.0-beta.20/vega-embed.js"></script>
  <title>{title}</title>

  <style media="screen">
    /* Add space between vega-embed links */
    /* http://vega.github.io/vega-tutorials/airports/ */
    .vega-embed .vega-actions a {{
      margin-left: 1em;
      visibility: hidden;
    }}
    .vega-embed:hover .vega-actions a {{
      visibility: visible;
    }}
  </style>
</head>
<body>

<div id="vis"></div>

<script type="text/javascript">
  var opt = {{
    "mode": "vega-lite",
  }};
  vega.embed('#vis', {spec}, opt);
</script>
</body>
</html>"""

readme = "# GPU Statistics\n\nData sourced from [Wikipedia's NVIDIA GPUs page](https://en.wikipedia.org/wiki/List_of_Nvidia_graphics_processing_units) and [Wikipedia's AMD GPUs page](https://en.wikipedia.org/wiki/List_of_AMD_graphics_processing_units).\n\n"

outputdir = "/Users/jowens/Documents/working/owensgroup/proj/gpustats/plots"
for (chart, title) in [(mb, "Memory Bandwidth over Time"),
                       (pr, "Processing Power over Time"),
                       (sm, "SM count over Time"),
                       (die, "Die Size over Time"),
                       (xt, "Transistor Count over Time",),
                       (fab, "Feature size over Time"),
                       (ai, "Arithmetic Intensity over Time"),
                       (fpw, "FLOPS per Watt over Time"),
                       (sh, "Shader count over Time")]:
    # save html
    # print chart.to_dict()
    with open(os.path.join(outputdir, title + '.html'), 'w') as f:
        spec = chart.to_dict()
        spec['height'] = 750
        spec['width'] = 1213
        spec['encoding']['tooltip'] = {"field": "Model", "type": "nominal"}
        f.write(template.format(spec=json.dumps(spec), title=title))
        # f.write(chart.from_json(spec_str).to_html(
        # title=title, template=template))
        save(chart, df=pd.DataFrame(), plotname=title, outputdir=outputdir,
             formats=['pdf'])
    readme += "- [%s](plots/%s.html)\n" % (title, title)

with open(os.path.join(outputdir, '../README.md'), 'w') as f:
    f.write(readme)
