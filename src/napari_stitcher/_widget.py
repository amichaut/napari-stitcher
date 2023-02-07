"""
This module is an example of a barebones QWidget plugin for napari

It implements the Widget specification.
see: https://napari.org/stable/plugins/guides.html?#widgets

Replace code below according to your needs.
"""
from typing import TYPE_CHECKING
import pathlib, os

import numpy as np
import dask
import dask.array as da

from napari.utils import notifications

from magicgui import magic_factory
from qtpy.QtWidgets import QVBoxLayout, QPushButton, QWidget

from magicgui import magicgui

from magicgui import widgets

from mvregfus import io_utils, mv_utils, mv_visualization

from napari_stitcher import _utils

if TYPE_CHECKING:
    import napari


class StitcherQWidget(QWidget):
    # your QWidget.__init__ can optionally request the napari viewer instance
    # in one of two ways:
    # 1. use a parameter called `napari_viewer`, as done here
    # 2. use a type annotation of 'napari.viewer.Viewer' for any parameter
    def __init__(self, napari_viewer):
        super().__init__()
        self.viewer = napari_viewer

        self.setLayout(QVBoxLayout())
        
        self.source_path = _utils.get_source_path_from_viewer(napari_viewer)
        if self.source_path is not None:
            default_outdir = self.source_path+'_stitched'
        else:
            default_outdir = os.path.join('.', 'napari_stitcher_output')
        self.outdir_picker = widgets.FileEdit(label='Output dir:',
                value=default_outdir, mode='r')

        self.button_load_metadata = widgets.Button(text='Load metadata')

        self.dimension_rbuttons = widgets.RadioButtons(
            choices=['2D', '3D'], label="Process in:", value="2D", enabled=False, orientation='horizontal')
        
        self.times_slider = widgets.RangeSlider(min=0, max=1, label='Timepoints', enabled=False)
        self.regch_slider = widgets.Slider(min=0, max=1, label='Reg channel', enabled=False)

        # self.button_visualize_input = widgets.Button(text='Visualize input', enabled=False)
        self.button_run = widgets.Button(text='Stitch', enabled=False)

        self.visualization_type_rbuttons = widgets.RadioButtons(
            choices=['Metadata', 'Registered'], label="Show:", value="Metadata", enabled=False,
            orientation='horizontal')

        # self.vis_ch_slider = widgets.Slider(min=0, max=1, label='Channel', enabled=False)
        # self.vis_times_slider = widgets.Slider(min=0, max=1, label='Timepoint', enabled=False)

        self.loading_widgets = [
                                
                                self.button_load_metadata,
                                self.outdir_picker,
                                ]

        self.reg_setting_widgets = [self.dimension_rbuttons,
                                    self.times_slider,
                                    self.regch_slider,
                                    self.button_run,
                                    ]

        self.visualization_widgets = [
                                      self.visualization_type_rbuttons,
        ]
        # self.visualization_widgets = [self.button_visualize_input,
        #                               self.visualization_type_rbuttons,
        #                               self.vis_ch_slider,
        #                               self.vis_times_slider,
        #                               ]


        self.container = widgets.VBox(widgets=\
                            self.loading_widgets+
                            self.reg_setting_widgets+
                            self.visualization_widgets
                            )
                                        
        self.layout().addWidget(self.container.native)

        self.params = dict()

        @self.visualization_type_rbuttons.changed.connect
        @self.viewer.dims.events.connect
        def update_slider(event):
            """
            set transformation for current timepoint
            """

            # get first view layer
            l = None
            for l in self.viewer.layers:
                if 'source_file' in l.metadata:
                    break
            if l is None: return

            is_timelapse = len(l.metadata['times']) > 1
            if not is_timelapse:
                return
            
            # # if parameters already set, do nothing
            # if l.metadata['parameter_type'] == \
            #     self.visualization_type_rbuttons.value: return

            curr_tp = self.viewer.dims.current_step[0]

            if self.visualization_type_rbuttons.value == 'Registered'\
                    and curr_tp not in self.params:
                notifications.notification_manager.receive_info(
                    'Timepoint %s: no parameters available' % curr_tp)
                self.visualization_type_rbuttons.value == 'Metadata'
                return

            for l in self.viewer.layers:
                if not 'source_file' in l.metadata: continue
                view, _ch = _utils.get_view_and_ch_from_layer_name(l.name)
                
                if self.visualization_type_rbuttons.value == 'Registered':
                    p = self.params[curr_tp][view]
                else:
                    p = mv_utils.matrix_to_params(np.eye(l.metadata['ndim'] + 1))

                # print(self.visualization_type_rbuttons.value, view, ch)

                p_napari = _utils.params_to_napari_affine(p,
                    l.metadata['stack_props'],
                    l.metadata['view_dict'])

                # embed parameters into ndim + 2 matrix because of time axis
                time_p = np.eye(l.metadata['ndim'] + 2)
                time_p[-len(p_napari):, -len(p_napari):] = p_napari
                
                # print(p_napari, time_p)
                l.affine.affine_matrix = time_p
                l.refresh()
           
        # self.viewer.dims.events.axis.connect(update_slider)
        # self.viewer.dims.events.connect(update_slider)


        @self.button_run.clicked.connect
        def run_sitching(value: str):

            max_project = True if self.dimension_rbuttons.value == '2D' else False

            self.view_dict = io_utils.build_view_dict_from_multitile_czi(self.source_path, max_project=max_project)
            self.views = np.array([view for view in sorted(self.view_dict.keys())])
            self.pairs = mv_utils.get_registration_pairs_from_view_dict(self.view_dict)

            print('lalalalal', self.view_dict)

            # if max_project or int(self.dims['Z'][1] <= 1):
            #     self.ndim = 2
            # else:
            #     self.ndim = 3

            pair_requires_registration = []
            for pair in self.pairs:

                slices_f, slices_m, lower_f_phys, lower_m_phys = \
                    mv_utils.get_overlap_between_pair_of_views(self.view_dict[pair[0]],
                                                               self.view_dict[pair[1]])

                if np.max([[s.start == s.stop for s in slices_f],
                           [s.start == s.stop for s in slices_m]]):
                    nonzero_overlap = False
                else: nonzero_overlap = True

                pair_requires_registration.append(nonzero_overlap)
            
            if not max(pair_requires_registration):
                message = 'No overlap between views, so no registration needs to be performed.'
                notifications.notification_manager.receive_info(message)
                return

            times = range(self.times_slider.value[0] + 1, self.times_slider.value[1] + 1)
            viewims = _utils.load_tiles(self.view_dict, [self.regch_slider.value],
                            times, max_project=max_project)

            times = range(self.times_slider.value[0] + 1, self.times_slider.value[1] + 1)

            # choose central view as reference
            ref_view_index = len(self.views) // 2
            ps = _utils.register_tiles(
                                viewims,
                                self.pairs,
                                reg_channel = self.regch_slider.value,
                                times = times,
                                registration_binning=[2] * len(self.view_dict[self.views[0]]['shape']),
                                ref_view_index = ref_view_index,
                                )

            from napari.utils import progress
            from tqdm.dask import TqdmCallback

            # make evident that processing is happening by disabling widgets
            # this command raises a warning regarding accessing a private attribute
            napari_viewer.window._status_bar._toggle_activity_dock(True)
            enabled = [w.enabled for w in self.container]
            for w in self.container:
                w.enabled = False

            with TqdmCallback(tqdm_class=progress, desc="Registering tiles"):
                psc = dask.compute(ps, scheduler='threading')[0]

            # enable widgets again
            for w, e in zip(self.container, enabled):
                w.enabled = e

            # this command raises a warning regarding accessing a private attribute
            # napari_viewer.window._status_bar._toggle_activity_dock(False)

            self.params.update(psc)
            self.visualization_type_rbuttons.enabled = True

        
        @self.button_load_metadata.clicked.connect
        def load_metadata(value: str):

            curr_source_path = _utils.get_source_path_from_viewer(self.viewer)
            if self.source_path != curr_source_path:
                self.params = dict()
                self.visualization_type_rbuttons.value = 'Metadata'
                self.visualization_type_rbuttons.enabled = False

            self.source_path = curr_source_path
            if self.source_path is None:
                notifications.notification_manager.receive_info('No CZI file loaded.')
                return

            self.dims = io_utils.get_dims_from_multitile_czi(self.source_path)
            print(self.dims)

            # self.view_dict = io_utils.build_view_dict_from_multitile_czi(self.source_path, max_project=True)
            # self.views = np.array([view for view in sorted(self.view_dict.keys())])
            # self.pairs = mv_utils.get_registration_pairs_from_view_dict(self.view_dict)
            # self.ndim = [2, 3][int(self.dims['Z'][1] > 1)]

            if self.dims['Z'][1] > 1:
                self.dimension_rbuttons.enabled = True
            else:
                self.dimension_rbuttons.enabled = False
            
            self.times_slider.min, self.times_slider.max = self.dims['T'][0] - 1, self.dims['T'][1] - 1
            self.times_slider.value = (self.dims['T'][0] - 1, self.dims['T'][0])

            self.regch_slider.min, self.regch_slider.max = self.dims['C'][0], self.dims['C'][1] - 1
            # self.regch_slider.value = self.dims['C'][0]

            for w in self.reg_setting_widgets:
                w.enabled = True

            # link channel layers
            from napari.experimental import link_layers
            for ch in range(self.dims['C'][0], self.dims['C'][1]):

                layers_to_link = [_utils.get_layer_from_view_and_ch(self.viewer, view, ch)
                    for view in range(self.dims['M'][0], self.dims['M'][1])]
                link_layers(layers_to_link, ('contrast_limits', 'visible'))


# simple widget to reload the plugin during development
def reload_plugin_widget(viewer: "napari.Viewer"):
    import importlib
    from napari_stitcher import _widget, _utils, _reader
    _widget = importlib.reload(_widget)
    _utils = importlib.reload(_utils)
    _reader = importlib.reload(_reader)

    from mvregfus import mv_visualization, mv_utils, io_utils
    mv_visualization = importlib.reload(mv_visualization)
    mv_utils = importlib.reload(mv_utils)
    io_utils = importlib.reload(io_utils)
    
    # viewer.window.remove_dock_widget('all')
    viewer.window.add_dock_widget(_widget.StitcherQWidget(viewer))
    

