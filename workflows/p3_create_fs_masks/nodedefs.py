"""Define Nodes for time shift and despike workflow

TODO

"""
import os
from ppp.base import basenodedefs
from .custom import *
from nipype.interfaces import afni,freesurfer,ants
from nipype.interfaces.io import BIDSDataGrabber
from nipype.interfaces.utility import Merge,Function
from nipype import Node,MapNode
from functools import reduce

class definednodes(basenodedefs):
    """Class initializing all nodes in workflow

        TODO

    """

    def __init__(self,settings):
        # call base constructor
        super().__init__(settings)

        # define input and output nodes
        self.set_input([
            'aparc_aseg',
            'orig',
            'affine_anat_2_atlas',
            'warp_anat_2_atlas',
            'anat_atlas',
            'func_atlas',
            'T1'
            ])

        # define datasink substitutions
        self.set_subs([
            ('_calc_calc_calc_calc_calc_Warped','_atlas')
        ])

        # define datasink substitutions
        #self.set_resubs([]])

        # convert freesurfer segmentation
        self.mri_convert = Node(
            freesurfer.MRIConvert(
                out_type='niigz'
            ),
            name='mri_convert'
        )

        # align freesurfer to anat
        self.align_fs_2_anat = Node(
            ants.Registration(
                num_threads=settings['num_threads'],
                collapse_output_transforms=False,
                initial_moving_transform_com=1,
                write_composite_transform=True,
                initialize_transforms_per_stage=True,
                transforms=['Rigid','Affine'],
                transform_parameters=[(0.1,),(0.1,)],
                metric=['MI','MI'],
                metric_weight=[1,1],
                radius_or_number_of_bins=[32,32],
                sampling_strategy=['Regular','Regular'],
                sampling_percentage=[0.25,0.25],
                convergence_threshold=[1.e-6,1.e-8],
                convergence_window_size=[10,10],
                smoothing_sigmas=[[3,2,1,0],[2,1,0]],
                sigma_units=['vox','vox'],
                shrink_factors=[[8,4,2,1],[4,2,1]],
                number_of_iterations=[[1000,500,250,100],[500,250,100]],
                use_estimate_learning_rate_once=[False,True],
                use_histogram_matching=False,
                verbose=True,
                output_warped_image=True
            ),
            name='align_fs_2_anat'
        )

        # join warps (leave defaults for nonlinear warp)
        self.join_warps = Node(
            Function(
                input_names=['refernce','affine_fs_2_anat','affine_anat_2_atlas','warp_anat_2_atlas'],
                output_names=['fs_concat_transform'],
                function=join_warps
            ),
            name='join_warps'
        )
        self.join_warps.inputs.reference = settings['atlas']

        # apply atlas alignment to aparc+aseg
        self.apply_warp = Node(
            Function(
                input_names=['in_file','reference','transform'],
                output_names=['out_file'],
                function=apply_warp
            ),
            name='apply_warp'
        )
        self.join_warps.inputs.reference = settings['atlas']

        # get the first run
        self.epi_firstrun = Node(
            Function(
                input_names=['epi_at'],
                output_names=['epi_at'],
                function=lambda x: x[0]
            ),
            name='epi_firstrun'
        )

        # extract the GM, WM, CSF, and WB compartments

        # everything labeled in FS, followed by resampling to the BOLD resolution
        self.calc1 = Node(
            afni.Calc(
                expr='not(equals(a,0))',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc1'
        )
        self.resample1 = Node(
            afni.Resample(
                outputtype='NIFTI_GZ',
                resample_mode='NN',
            ),
            name='resample1'
        )

        # the major WM compartments, with 4 erosions at the T1 resolution followed by resampling to the BOLD resolution
        self.calc2_wm = Node(
            afni.Calc(
                expr='equals(a,2)+equals(a,7)+equals(a,41)+equals(a,46)+equals(a,251)+equals(a,252)+equals(a,253)+equals(a,254)+equals(a,255)',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc2_wm'
        )
        self.calc3_wm = []
        for n in range(4):
            self.calc3_wm.append(Node(
                afni.Calc(
                    args='-b a+i -c a-i -d a+j -e a-j -f a+k -g a-k',
                    expr='a*(1-amongst(0,b,c,d,e,f,g))',
                    outputtype='NIFTI_GZ',
                    overwrite=True
                ),
                name='calc3_wm_{}'.format(n)
            ))
        self.resample2_wm = []
        for n in range(5):
            self.resample2_wm.append(Node(
                afni.Resample(
                    outputtype='NIFTI_GZ',
                    resample_mode='NN',
                ),
                name='resample2_wm_{}'.format(n)
            ))

        # the major CSF compartments, with 4 erosions at the T1 resolution followed by resampling to the BOLD resolution
        self.calc2_csf = Node(
            afni.Calc(
                expr='equals(a,4)+equals(a,43)+equals(a,14)',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc2_csf'
        )
        self.calc3_csf = []
        for n in range(4):
            self.calc3_csf.append(Node(
                afni.Calc(
                    args='-b a+i -c a-i -d a+j -e a-j -f a+k -g a-k',
                    expr='a*(1-amongst(0,b,c,d,e,f,g))',
                    outputtype='NIFTI_GZ',
                    overwrite=True
                ),
                name='calc3_csf_{}'.format(n)
            ))
        self.resample2_csf = []
        for n in range(5):
            self.resample2_csf.append(Node(
                afni.Resample(
                    outputtype='NIFTI_GZ',
                    resample_mode='NN',
                ),
                name='resample2_csf_{}'.format(n)
            ))

        # the gray matter ribbon (amygdala and hippocampus need to be added - 17 18 53 54
        self.calc2_gmr = Node(
            afni.Calc(
                expr='within(a,1000,3000)+equals(a,17)+equals(a,18)+equals(a,53)+equals(a,54)',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc2_gmr'
        )
        self.resample2_gmr = Node(
            afni.Resample(
                outputtype='NIFTI_GZ',
                resample_mode='NN',
            ),
            name='resample2_gmr'
        )

        # the cerebellum
        self.calc2_cb = Node(
            afni.Calc(
                expr='equals(a,47)+equals(a,8)',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc2_cb'
        )
        self.calc3_cb = []
        for n in range(2):
            self.calc3_cb.append(Node(
                afni.Calc(
                    args='-b a+i -c a-i -d a+j -e a-j -f a+k -g a-k',
                    expr='a*(1-amongst(0,b,c,d,e,f,g))',
                    outputtype='NIFTI_GZ',
                    overwrite=True
                ),
                name='calc3_cb_{}'.format(n)
            ))
        self.resample2_cb = []
        for n in range(3):
            self.resample2_cb.append(Node(
                afni.Resample(
                    outputtype='NIFTI_GZ',
                    resample_mode='NN',
                ),
                name='resample2_cb_{}'.format(n)
            ))

        # the subcortical nuclei
        self.calc2_scn = Node(
            afni.Calc(
                expr='equals(a,11)+equals(a,12)+equals(a,10)+equals(a,49)+equals(a,50)+equals(a,51)',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc2_scn'
        )
        self.calc3_scn = []
        for n in range(2):
            self.calc3_scn.append(Node(
                afni.Calc(
                    args='-b a+i -c a-i -d a+j -e a-j -f a+k -g a-k',
                    expr='a*(1-amongst(0,b,c,d,e,f,g))',
                    outputtype='NIFTI_GZ',
                    overwrite=True
                ),
                name='calc3_scn_{}'.format(n)
            ))
        self.resample2_scn = []
        for n in range(3):
            self.resample2_scn.append(Node(
                afni.Resample(
                    outputtype='NIFTI_GZ',
                    resample_mode='NN',
                ),
                name='resample2_scn_{}'.format(n)
            ))

        # all gray matter
        self.calc2_gm = Node(
            afni.Calc(
                expr='within(a,1000,3000)+equals(a,17)+equals(a,18)+equals(a,53)+equals(a,54)+equals(a,47)+equals(a,8)+equals(a,11)+equals(a,12)+equals(a,10)+equals(a,49)+equals(a,50)+equals(a,51)',
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            name='calc2_gm'
        )
        self.resample2_gm = Node(
            afni.Resample(
                outputtype='NIFTI_GZ',
                resample_mode='NN',
            ),
            name='resample2_gm'
        )

        # and finally create images of the atlas and the MPRAGE and the FS segmentation, resampled to BOLD resolution
        self.epi_resampled = Node(
            Function(
                input_names=['T1','epi','aparc_aseg'],
                output_names=['T1_epi','aparc_aseg_epi'],
                function=resample_2_epi
            ),
            name='epi_resampled'
        )
