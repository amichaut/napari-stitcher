"""
This module is an example of a barebones writer plugin for napari.

It implements the Writer specification.
see: https://napari.org/stable/plugins/guides.html?#writers

Replace code below according to your needs.
"""
from __future__ import annotations

from tifffile import imwrite, imread
import zarr

import numpy as np
import dask.array as da
from dask import config as dask_config

from typing import TYPE_CHECKING, Any, List, Sequence, Tuple, Union

if TYPE_CHECKING:
    DataType = Union[Any, Sequence[Any]]
    FullLayerData = Tuple[DataType, dict, str]


def write_single_image(path: str, data: Any, meta: dict) -> List[str]:
    """Writes a single image layer"""

    # implement your writer logic here ...

    # return path to any file(s) that were successfully written
    return [path]


def write_multiple(path: str, data: List[FullLayerData]) -> List[str]:
    """Writes zarr backed dask arrays containing fused images.
    FullLayerData: 3-tuple with (data, meta, layer_type)
    """

    # implement your writer logic here ...

    if not path.endswith('.tif'):
        raise ValueError('Only .tif file saving is supported.')

    if not np.all([d[1]['metadata']['view'] == -1 for d in data]):
        raise ValueError('Only saving of fused images is supported.')

    # spacing = data[0][1]['metadata']['stack_props']['spacing']
    # times = data[0][1]['metadata']['times']
    # channels = range(len(data))

    # suboptimal way of handling the physical pixel sizes
    views = list(data[0][1]['metadata']['view_dict'].keys())
    physical_pixel_sizes = data[0][1]['metadata']['view_dict'][views[0]]["physical_pixel_sizes"]

    array_to_write = da.stack([d[0].squeeze() for d in data])

    # currently hard coded and only 2d supported
    if array_to_write[0].ndim > 2:
        if len(data) > 1:
            axes = 'TCYX'
            array_to_write = da.swapaxes(array_to_write, 0, 1)
            chunk_shape = (1, 1) + array_to_write.shape[-2:]
        else:
            axes = 'TYX'
            array_to_write = array_to_write[0]
            chunk_shape = (1, ) + array_to_write.shape[-2:]
    else:
        if len(data) > 1:
            axes = 'CYX'
            chunk_shape = (1, ) + array_to_write.shape[-2:]
        else:
            axes = 'YX'
            array_to_write = array_to_write[0]
            chunk_shape = array_to_write.shape[-2:]

    # input dask array contains axes order 'ctyx'
    # output tiff file should have axes order 'tcyx'
    array_to_write = array_to_write.rechunk(chunk_shape)

    imwrite(
        path,
        shape=array_to_write.shape,
        dtype=array_to_write.dtype,
        imagej=True,
        resolution=tuple([1. / s for s in physical_pixel_sizes]),
        metadata={'axes': axes,
                  'unit': 'um'}
    )

    store = imread(path, mode='r+', aszarr=True)
    z = zarr.open(store, mode='r+')

    # writing with tifffile is not thread safe,
    # so we need to disable dask's multithreading
    with dask_config.set(scheduler='single-threaded'):
        da.store(array_to_write, z)#, compute=False)

    store.close()

    # return path to any file(s) that were successfully written

    return [path]
