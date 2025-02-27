# -*- coding: utf-8 -*-
# Copyright (c) 2020-2021 Salvador E. Tropea
# Copyright (c) 2020-2021 Instituto Nacional de Tecnología Industrial
# License: GPL-3.0
# Project: KiBot (formerly KiPlot)
import os
from copy import deepcopy
from .gs import GS
from .kiplot import load_sch, get_board_comps_data
from .misc import Rect, W_WRONGPASTE
if not GS.kicad_version_n:
    # When running the regression tests we need it
    from kibot.__main__ import detect_kicad
    detect_kicad()
if GS.ki6():  # pragma: no cover (Ki6)
    # New name, no alias ...
    from pcbnew import FP_SHAPE, wxPoint, LSET
else:
    from pcbnew import EDGE_MODULE, wxPoint, LSET
from .registrable import RegOutput
from .optionable import Optionable, BaseOptions
from .fil_base import BaseFilter, apply_fitted_filter, reset_filters
from .macros import macros, document  # noqa: F401
from .error import KiPlotConfigurationError
from . import log

logger = log.get_logger()


class BaseOutput(RegOutput):
    def __init__(self):
        super().__init__()
        with document:
            self.name = ''
            """ Used to identify this particular output definition """
            self.type = ''
            """ Type of output """
            self.dir = './'
            """ Output directory for the generated files. If it starts with `+` the rest is concatenated to the default dir """
            self.comment = ''
            """ A comment for documentation purposes """
            self.extends = ''
            """ Copy the `options` section from the indicated output """
            self.run_by_default = True
            """ When enabled this output will be created when no specific outputs are requested """
            self.disable_run_by_default = ''
            """ [string|boolean] Use it to disable the `run_by_default` status of other output.
                Useful when this output extends another and you don't want to generate the original.
                Use the boolean true value to disable the output you are extending """
            self.output_id = ''
            """ Text to use for the %I expansion content. To differentiate variations of this output """
        if GS.global_dir:
            self.dir = GS.global_dir
        self._sch_related = False
        self._both_related = False
        self._unkown_is_error = True
        self._done = False

    @staticmethod
    def attr2longopt(attr):
        return '--'+attr.replace('_', '-')

    def is_sch(self):
        """ True for outputs that works on the schematic """
        return self._sch_related or self._both_related

    def is_pcb(self):
        """ True for outputs that works on the PCB """
        return (not self._sch_related) or self._both_related

    def get_targets(self, out_dir):
        """ Returns a list of targets generated by this output """
        if not (hasattr(self, "options") and hasattr(self.options, "get_targets")):
            logger.error("Output {} doesn't implement get_targets(), plese report it".format(self))
            return []
        return self.options.get_targets(out_dir)

    def get_dependencies(self):
        """ Returns a list of files needed to create this output """
        if self._sch_related:
            if GS.sch:
                return GS.sch.get_files()
            return [GS.sch_file]
        return [GS.pcb_file]

    def config(self, parent):
        if self._tree and not self._configured and isinstance(self.extends, str) and self.extends:
            logger.debug("Extending `{}` from `{}`".format(self.name, self.extends))
            # Copy the data from the base output
            out = RegOutput.get_output(self.extends)
            if out is None:
                raise KiPlotConfigurationError('Unknown output `{}` in `extends`'.format(self.extends))
            if out._tree:
                options = out._tree.get('options', None)
                if options:
                    old_options = self._tree.get('options', {})
                    # logger.error("Old options: "+str(old_options))
                    options = deepcopy(options)
                    options.update(old_options)
                    self._tree['options'] = options
                    # logger.error("New options: "+str(options))
        super().config(parent)
        to_dis = self.disable_run_by_default
        if isinstance(to_dis, str) and to_dis:  # Skip the boolean case
            out = RegOutput.get_output(to_dis)
            if out is None:
                raise KiPlotConfigurationError('Unknown output `{}` in `disable_run_by_default`'.format(to_dis))
        if self.dir[0] == '+':
            self.dir = (GS.global_dir if GS.global_dir is not None else './') + self.dir[1:]
        if getattr(self, 'options', None) and isinstance(self.options, type):
            # No options, get the defaults
            self.options = self.options()
            # Configure them using an empty tree
            self.options.config(self)

    def expand_dirname(self, out_dir):
        return self.options.expand_filename_both(out_dir, is_sch=self._sch_related)

    def expand_filename(self, out_dir, name):
        name = self.options.expand_filename_both(name, is_sch=self._sch_related)
        return os.path.abspath(os.path.join(out_dir, name))

    def run(self, output_dir):
        self.output_dir = output_dir
        self.options.run(self.expand_filename(output_dir, self.options.output))


class BoMRegex(Optionable):
    """ Implements the pair column/regex """
    def __init__(self):
        super().__init__()
        self._unkown_is_error = True
        with document:
            self.column = ''
            """ Name of the column to apply the regular expression """
            self.regex = ''
            """ Regular expression to match """
            self.field = None
            """ {column} """
            self.regexp = None
            """ {regex} """
            self.skip_if_no_field = False
            """ Skip this test if the field doesn't exist """
            self.match_if_field = False
            """ Match if the field exists, no regex applied. Not affected by `invert` """
            self.match_if_no_field = False
            """ Match if the field doesn't exists, no regex applied. Not affected by `invert` """
            self.invert = False
            """ Invert the regex match result """


class VariantOptions(BaseOptions):
    """ BaseOptions plus generic support for variants. """
    def __init__(self):
        with document:
            self.variant = ''
            """ Board variant to apply """
            self.dnf_filter = Optionable
            """ [string|list(string)='_none'] Name of the filter to mark components as not fitted.
                A short-cut to use for simple cases where a variant is an overkill """
        super().__init__()
        self._comps = None

    def config(self, parent):
        super().config(parent)
        self.variant = RegOutput.check_variant(self.variant)
        self.dnf_filter = BaseFilter.solve_filter(self.dnf_filter, 'dnf_filter')

    def get_refs_hash(self):
        if not self._comps:
            return None
        return {c.ref: c for c in self._comps}

    def get_fitted_refs(self):
        """ List of fitted and included components """
        if not self._comps:
            return []
        return [c.ref for c in self._comps if c.fitted and c.included]

    def get_not_fitted_refs(self):
        """ List of 'not fitted' components, also includes 'not included' """
        if not self._comps:
            return []
        return [c.ref for c in self._comps if not c.fitted or not c.included]

    @staticmethod
    def create_module_element(m):
        if GS.ki6():
            return FP_SHAPE(m)  # pragma: no cover (Ki6)
        return EDGE_MODULE(m)

    @staticmethod
    def cross_module(m, rect, layer):
        """ Draw a cross over a module.
            The rect is a Rect object with the size.
            The layer is which layer id will be used. """
        seg1 = VariantOptions.create_module_element(m)
        seg1.SetWidth(120000)
        seg1.SetStart(wxPoint(rect.x1, rect.y1))
        seg1.SetEnd(wxPoint(rect.x2, rect.y2))
        seg1.SetLayer(layer)
        seg1.SetLocalCoord()  # Update the local coordinates
        m.Add(seg1)
        seg2 = VariantOptions.create_module_element(m)
        seg2.SetWidth(120000)
        seg2.SetStart(wxPoint(rect.x1, rect.y2))
        seg2.SetEnd(wxPoint(rect.x2, rect.y1))
        seg2.SetLayer(layer)
        seg2.SetLocalCoord()  # Update the local coordinates
        m.Add(seg2)
        return [seg1, seg2]

    def cross_modules(self, board, comps_hash):
        """ Draw a cross in all 'not fitted' modules using *.Fab layer """
        if comps_hash is None:
            return
        # Cross the affected components
        ffab = board.GetLayerID('F.Fab')
        bfab = board.GetLayerID('B.Fab')
        extra_ffab_lines = []
        extra_bfab_lines = []
        for m in GS.get_modules_board(board):
            ref = m.GetReference()
            # Rectangle containing the drawings, no text
            frect = Rect()
            brect = Rect()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                # Meassure the component BBox (only graphics)
                for gi in m.GraphicalItems():
                    if gi.GetClass() == 'MGRAPHIC':
                        l_gi = gi.GetLayer()
                        if l_gi == ffab:
                            frect.Union(gi.GetBoundingBox().getWxRect())
                        if l_gi == bfab:
                            brect.Union(gi.GetBoundingBox().getWxRect())
                # Cross the graphics in *.Fab
                if frect.x1 is not None:
                    extra_ffab_lines.append(self.cross_module(m, frect, ffab))
                else:
                    extra_ffab_lines.append(None)
                if brect.x1 is not None:
                    extra_bfab_lines.append(self.cross_module(m, brect, bfab))
                else:
                    extra_bfab_lines.append(None)
        # Remmember the data used to undo it
        self.extra_ffab_lines = extra_ffab_lines
        self.extra_bfab_lines = extra_bfab_lines

    def uncross_modules(self, board, comps_hash):
        """ Undo the crosses in *.Fab layer """
        if comps_hash is None:
            return
        # Undo the drawings
        for m in GS.get_modules_board(board):
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                restore = self.extra_ffab_lines.pop(0)
                if restore:
                    for line in restore:
                        m.Remove(line)
                restore = self.extra_bfab_lines.pop(0)
                if restore:
                    for line in restore:
                        m.Remove(line)

    def remove_paste_and_glue(self, board, comps_hash):
        """ Remove from solder paste layers the filtered components. """
        if comps_hash is None:
            return
        exclude = LSET()
        fpaste = board.GetLayerID('F.Paste')
        bpaste = board.GetLayerID('B.Paste')
        exclude.addLayer(fpaste)
        exclude.addLayer(bpaste)
        old_layers = []
        fadhes = board.GetLayerID('F.Adhes')
        badhes = board.GetLayerID('B.Adhes')
        old_fadhes = []
        old_badhes = []
        rescue = board.GetLayerID(GS.work_layer)
        fmask = board.GetLayerID('F.Mask')
        bmask = board.GetLayerID('B.Mask')
        for m in GS.get_modules_board(board):
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                # Remove all pads from *.Paste
                old_c_layers = []
                for p in m.Pads():
                    pad_layers = p.GetLayerSet()
                    is_front = fpaste in pad_layers.Seq()
                    old_c_layers.append(pad_layers.FmtHex())
                    pad_layers.removeLayerSet(exclude)
                    if len(pad_layers.Seq()) == 0:
                        # No layers at all. Ridiculous, but happends.
                        # At least add an F.Mask
                        pad_layers.addLayer(fmask if is_front else bmask)
                        logger.warning(W_WRONGPASTE+'Pad with solder paste, but no copper or solder mask aperture in '+ref)
                    p.SetLayerSet(pad_layers)
                old_layers.append(old_c_layers)
                # Remove any graphical item in the *.Adhes layers
                for gi in m.GraphicalItems():
                    l_gi = gi.GetLayer()
                    if l_gi == fadhes:
                        gi.SetLayer(rescue)
                        old_fadhes.append(gi)
                    if l_gi == badhes:
                        gi.SetLayer(rescue)
                        old_badhes.append(gi)
        # Store the data to undo the above actions
        self.old_layers = old_layers
        self.old_fadhes = old_fadhes
        self.old_badhes = old_badhes
        self.fadhes = fadhes
        self.badhes = badhes
        return exclude

    def restore_paste_and_glue(self, board, comps_hash):
        if comps_hash is None:
            return
        for m in GS.get_modules_board(board):
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                restore = self.old_layers.pop(0)
                for p in m.Pads():
                    pad_layers = p.GetLayerSet()
                    res = restore.pop(0)
                    pad_layers.ParseHex(res, len(res))
                    p.SetLayerSet(pad_layers)
        for gi in self.old_fadhes:
            gi.SetLayer(self.fadhes)
        for gi in self.old_badhes:
            gi.SetLayer(self.badhes)

    def remove_fab(self, board, comps_hash):
        """ Remove from Fab the excluded components. """
        if comps_hash is None:
            return
        ffab = board.GetLayerID('F.Fab')
        bfab = board.GetLayerID('B.Fab')
        old_ffab = []
        old_bfab = []
        rescue = board.GetLayerID(GS.work_layer)
        for m in GS.get_modules_board(board):
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if not c.included:
                # Remove any graphical item in the *.Fab layers
                for gi in m.GraphicalItems():
                    l_gi = gi.GetLayer()
                    if l_gi == ffab:
                        gi.SetLayer(rescue)
                        old_ffab.append(gi)
                    if l_gi == bfab:
                        gi.SetLayer(rescue)
                        old_bfab.append(gi)
        # Store the data to undo the above actions
        self.old_ffab = old_ffab
        self.old_bfab = old_bfab
        self.ffab = ffab
        self.bfab = bfab

    def restore_fab(self, board, comps_hash):
        if comps_hash is None:
            return
        for gi in self.old_ffab:
            gi.SetLayer(self.ffab)
        for gi in self.old_bfab:
            gi.SetLayer(self.bfab)

    def set_title(self, title):
        self.old_title = None
        if title:
            tb = GS.board.GetTitleBlock()
            self.old_title = tb.GetTitle()
            text = self.expand_filename_pcb(title)
            if text[0] == '+':
                text = self.old_title+text[1:]
            tb.SetTitle(text)

    def restore_title(self):
        self.old_title = None
        if self.old_title is not None:
            GS.board.GetTitleBlock().SetTitle(self.old_title)

    def run(self, output_dir):
        """ Makes the list of components available """
        if not self.dnf_filter and not self.variant:
            return
        load_sch()
        # Get the components list from the schematic
        comps = GS.sch.get_components()
        get_board_comps_data(comps)
        # Apply the filter
        reset_filters(comps)
        apply_fitted_filter(comps, self.dnf_filter)
        # Apply the variant
        if self.variant:
            # Apply the variant
            comps = self.variant.filter(comps)
        self._comps = comps
