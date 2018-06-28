"""Define Nodes for skullstrip workflow

TODO

"""
from ..base import basenodedefs
from nipype import Node,MapNode
from nipype.interfaces import afni,fsl
from nipype.interfaces.utility import IdentityInterface,Function

class definednodes(basenodedefs):
    """Class initializing all nodes in workflow

        TODO

    """

    def __init__(self,settings):
        # call base constructor
        super().__init__(settings)

        # define input node
        self.inputnode = Node(
            IdentityInterface(
                fields=['T1','orig','brainmask']
            ),
            name='input'
        )

        # identity interface for inputting T1 images
        self.T1imgs = Node(
            IdentityInterface(
                fields=['T1']
            ),
            name='T1imgs'
        )

        # 3dAllineate (FSorig)
        self.allineate_orig = MapNode(
            afni.Allineate(
                out_matrix='FSorig2MPR.aff12.1D',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','reference'],
            name='3dallineate_orig'
        )
        # 3dAllineate (FSbrainmask)
        self.allineate_bm = MapNode(
            afni.Allineate(
                overwrite=True,
                no_pad=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','reference','in_matrix'],
            name='3dallineate_brainmask'
        )

        # skullstrip mprage (afni)
        self.afni_skullstrip = MapNode(
            afni.SkullStrip(
                args="-orig_vol",
                outputtype="NIFTI_GZ"
            ),
            iterfield=['in_file'],
            name='afni_skullstrip'
        )
        # 3dcalc operations for achieving final mask
        self.maskop1 = MapNode(
            afni.Calc(
                expr='step(a)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file_a'],
            name='maskop1'
        )
        self.maskop2 = []
        for n in range(3):
            self.maskop2.append(MapNode(
                afni.Calc(
                    args='-b a+i -c a-i -d a+j -e a-j -f a+k -g a-k',
                    expr='ispositive(a+b+c+d+e+f+g)',
                    overwrite=True,
                    outputtype='NIFTI_GZ'
                ),
                iterfield=['in_file_a'],
                name='maskop2_{}'.format(n)
            ))
        # Inline function for setting up to copy IJK_TO_DICOM_REAL file attribute
        self.refit_setup = MapNode(
            Function(
                input_names=['noskull_T1'],
                output_names=['refit_input'],
                function=lambda noskull_T1: (noskull_T1,'IJK_TO_DICOM_REAL')
            ),
            iterfield=['noskull_T1'],
            name='refitsetup'
        )
        # 3dRefit
        self.refit = MapNode(
            afni.Refit(),
            iterfield=['in_file','atrcopy'],
            name='3drefit'
        )
        # 3dcalc for uniform intensity
        self.uniform = MapNode(
            afni.Calc(
                expr='a*and(b,b)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file_a','in_file_b'],
            name='uniformintensity'
        )

        # skullstrip mprage (fsl)
        self.fsl_skullstrip = MapNode(
            fsl.BET(),
            iterfield=['in_file'],
            name='fsl_skullstrip'
        )
        self.maskop3 = MapNode(
            afni.Calc(
                expr='or(a,b,c)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file_a','in_file_b','in_file_c'],
            name='maskop3'
        )
        self.maskop4 = MapNode(
            afni.Calc(
                expr='c*and(a,b)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file_a','in_file_b','in_file_c'],
            name='maskop4'
        )

        # define output node
        self.outputnode = Node(
            IdentityInterface(
                fields=['skullstripped_mprage']
            ),
            name='output'
        )