"""
    Define Nodes for nipype workflow
"""
import os
from nipype import Node,MapNode,IdentityInterface
from nipype.interfaces import afni,fsl,freesurfer
from nipype.interfaces.io import SelectFiles,DataSink
from nipype.interfaces.utility import Function,IdentityInterface,Rename,Merge
from custom import * # import our custom functions/interfaces

class definednodes:
    """
        Class initializing all nodes in workflow
    """

    def __init__(self,settings):
        """
            Initialize settings and define nodes
        """

        # Define several directoris to use
        self.BASE_DIR = settings['BASE_DIR']
        self.SUBJECTS_DIR = os.path.join(self.BASE_DIR,'output','freesurfer_output')
        self.TMP_DIR = os.path.join(self.BASE_DIR,'tmp')
        self.REF_IMGS = os.path.join(self.BASE_DIR,'refimgs')

        # make directories if not exist
        os.makedirs(self.SUBJECTS_DIR,exist_ok=True)
        os.makedirs(self.TMP_DIR,exist_ok=True)

        # set number of initial frames to ignore
        self.IGNOREFRAMES = settings['ignoreframes']

        # Create an Identity interface to select subjects
        self.infosource = Node(
            IdentityInterface(
                fields=['subject_id']
            ),
            iterables = [('subject_id',['sub-CTS200'])],
            name='infosource'
        )

        # Select epis and T1s (and their sidecars)
        self.fileselection = Node(
            SelectFiles(
                {
                    'epi': os.path.join(self.BASE_DIR,'dataset','{subject_id}','func','*baseline*.nii.gz'),
                    'epi_sidecar': os.path.join(self.BASE_DIR,'dataset','{subject_id}','func','*baseline*.json'),
                    'T1': os.path.join(self.BASE_DIR,'dataset','{subject_id}','anat','*T1w*.nii.gz'),
                    'T1_sidecar': os.path.join(self.BASE_DIR,'dataset','{subject_id}','anat','*T1w*.json')
                }
            ),
            name='selectfiles'
        )

        # Do QC on all files
        self.QC = MapNode(
            Function(
                input_names=['epi','epi_sidecar'],
                output_names=['QClist'],
                function=qualitycheck
            ),
            iterfield=['epi','epi_sidecar'],
            name='QC'
        )

        # Reduce set based on QC check
        self.QCreduce = Node(
            Function(
                input_names=['QClist'],
                output_names=['epi','epi_sidecar'],
                function=QCreduceset
            ),
            name='QCreduce'
        )

        # Despike epi data (create 2 for permutations with slice time correction)
        self.despike = []
        for n in range(2):
            self.despike.append(MapNode(
                ExtendedDespike(
                    args="-ignore {} -NEW -nomask".format(
                        self.IGNOREFRAMES
                    ),
                    outputtype="NIFTI_GZ"
                ),
                iterfield=['in_file'],
                name='despike{}'.format(n)
            ))

        # extract slice timing so we can pass it to slice time correction
        self.extract_stc = MapNode(
            Function(
                input_names=['epi_sidecar'],
                output_names=['slicetiming','TR'],
                function=extract_slicetime
            ),
            iterfield=['epi_sidecar'],
            name='extract_slicetime'
        )

        # timeshift data (create 2 for permutations with despiking)
        self.tshift = []
        for n in range(2):
            self.tshift.append(MapNode(
                afni.TShift(
                    args="-heptic",
                    ignore=self.IGNOREFRAMES,
                    tzero=0,
                    outputtype="NIFTI_GZ"
                ),
                iterfield=['in_file','tpattern','tr'],
                name='tshift{}'.format(n)
            ))

        # Setup basefile for volreg
        self.firstrunonly = Node( # this will create a list of the first run to feed as a basefile
            Function(
                input_names=['epi'],
                output_names=['epi'],
                function=lambda epi: [epi[0] for item in epi]
            ),
            name='retrievefirstrun'
        )

        self.extractroi = []
        for n in range(2): # create 2 nodes to align to first run and each run
            self.extractroi.append(MapNode(
                fsl.ExtractROI(
                    t_min=self.IGNOREFRAMES,
                    t_size=1,
                    output_type='NIFTI_GZ'
                ),
                iterfield=['in_file'],
                name='extractroi{}'.format(n)
            ))

        # Motion correction (create 10 nodes for different permutations of inputs)
        self.volreg = []
        for n in range(10):
            self.volreg.append(MapNode(
                afni.Volreg(
                    args="-heptic -maxite {}".format(
                        25
                    ),
                    verbose=True,
                    zpad=10,
                    outputtype="NIFTI_GZ"
                ),
                iterfield=['basefile','in_file'],
                name='volreg{}'.format(n)
            ))

        # Skullstrip
        # skullstrip mprage (afni)
        self.afni_skullstrip = Node(
            afni.SkullStrip(
                args="-orig_vol",
                outputtype="NIFTI_GZ"
            ),
            name='afni_skullstrip'
        )
        # skullstrip mprage (fsl)
        self.fsl_skullstrip = Node(
            fsl.BET(),
            name='fsl_skullstrip'
        )

        # Recon-all
        self.reconall = Node(
            freesurfer.ReconAll(
                directive='all',
                subjects_dir=self.SUBJECTS_DIR,
                parallel=True,
                openmp=4
            ),
            name='reconall'
        )

        # MRIConvert
        self.orig_convert = Node(
            freesurfer.MRIConvert(
                in_type='mgz',
                out_type='niigz'
            ),
            name='orig_mriconvert'
        )
        self.brainmask_convert = Node(
            freesurfer.MRIConvert(
                in_type='mgz',
                out_type='niigz'
            ),
            name='brainmask_mriconvert'
        )

        # 3dAllineate (FSorig)
        self.allineate_orig = Node(
            afni.Allineate(
                out_matrix='FSorig.XFM.FS2MPR.aff12.1D',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='3dallineate_orig'
        )

        # Inline function for setting up to copy IJK_TO_DICOM_REAL file attribute
        self.refit_setup = Node(
            Function(
                input_names=['noskull_T1'],
                output_names=['refit_input'],
                function=lambda noskull_T1: (noskull_T1,'IJK_TO_DICOM_REAL')
            ),
            name='refitsetup'
        )

        # 3dRefit (Create 2, one for FSorig and one for FSbrainmask)
        self.refit = []
        for n in range(2):
            self.refit.append(Node(
                afni.Refit(),
                name='3drefit{}'.format(n)
            ))

        # 3dAllineate (FSbrainmask)
        self.allineate_bm = Node(
            afni.Allineate(
                overwrite=True,
                no_pad=True,
                outputtype='NIFTI_GZ'
            ),
            name='3dallineate_brainmask'
        )

        # 3dcalc for uniform intensity
        self.uniform = Node(
            afni.Calc(
                expr='a*and(b,b)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='uniformintensity'
        )

        # 3dcalc operations for achieving final mask
        self.maskop1 = Node(
            afni.Calc(
                expr='step(a)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='maskop1'
        )
        self.maskop2 = []
        for n in range(3):
            self.maskop2.append(Node(
                afni.Calc(
                    args='-b a+i -c a-i -d a+j -e a-j -f a+k -g a-k',
                    expr='ispositive(a+b+c+d+e+f+g)',
                    overwrite=True,
                    outputtype='NIFTI_GZ'
                ),
                name='maskop2_{}'.format(n)
            ))
        self.maskop3 = Node(
            afni.Calc(
                expr='and(a,or(b,c))',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='maskop3'
        )
        self.maskop4 = Node(
            afni.Calc(
                expr='a*b',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='maskop4'
        )
        self.maskop5 = Node(
            afni.Calc(
                expr='or(a,b,c)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='maskop5'
        )
        self.maskop6 = Node(
            afni.Calc(
                expr='c*and(a,b)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            name='maskop6'
        )

        # Register to Atlas
        self.register = []
        for n in range(2):
            self.register.append(Node(
                Function(
                    input_names=['in_file'],
                    output_names=['out_file','transform_file'],
                    function=register_atlas
                ),
                name='atlasregister_{}'.format(n)
            ))

        # Transform the unskullstripped image
        self.allineate_unskullstripped = []
        for n in range(2):
            self.allineate_unskullstripped.append(Node(
                afni.Allineate(
                    overwrite=True,
                    reference=os.path.join(self.REF_IMGS,'TT_N27.nii.gz'),
                    outputtype='NIFTI_GZ'
                ),
                name='3dallineate_unskullstripped_{}'.format(n)
            ))

        # Skullstrip the EPI image
        self.epi_skullstrip = MapNode(
            fsl.BET(),
            iterfield=['in_file'],
            name='epi_skullstrip'
        )
        self.epi_automask = MapNode(
            afni.Automask(
                args='-overwrite',
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file'],
            name='epi_automask'
        )
        self.epi_3dcalc = MapNode(
            afni.Calc(
                expr='c*or(a,b)',
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file_a','in_file_b','in_file_c'],
            name='epi_3dcalc'
        )

        # deoblique the MPRAGE and compute the transform between EPIREF and MPRAGE obliquity
        self.warp_args = Node(
            IdentityInterface(
                fields=['args']
            ),
            name='warp_args'
        )
        self.warp_args.inputs.args = '-newgrid 1.000000'
        self.warp = MapNode(
            Function(
                input_names=['in_file','card2oblique','args'],
                output_names=['out_file','ob_transform'],
                function=warp_custom
            ),
            iterfield=['in_file','card2oblique'],
            name='3dwarp'
        )

        # resample the EPIREF to the MPRAGE
        self.resample = MapNode(
            afni.Resample(
                resample_mode='Cu',
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','master'],
            name='resample'
        )

        # calculate a weight mask for the lpc weighting
        self.weightmask = MapNode(
            Function(
                input_names=['in_file','no_skull'],
                output_names=['out_file'],
                function=create_weightmask
            ),
            iterfield=['in_file','no_skull'],
            name='weightmask'
        )

        # register the mprage to the tcat (BASE=TARGET, REGISTER TO THIS SPACE; SOURCE=INPUT, LEAVE THIS SPACE)
        # this registration is on images with the same grids, whose obliquity has been accounted for
        self.registert12tcat = MapNode(
            afni.Allineate(
                args='-lpc -nocmass -weight_frac 1.0 -master SOURCE',
                maxrot=6,
                maxshf=10,
                verbose=True,
                warp_type='affine_general',
                source_automask=4,
                two_pass=True,
                two_best=11,
                out_matrix='t12tcat_transform_mat.aff12.1D',
                out_weight_file='t12tcat_transform_weight_file.nii.gz',
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','weight','reference'],
            name='registermpragetotcat'
        )

        # Transfrom rawEPI into ATL space
        # Concatenate MPR-ATL -I, OMMPR-OBEMPI and MPR-EPI -I into a master transform
        self.mastertransform = MapNode(
            Function(
                input_names=['in_file','transform1','transform2'],
                output_names=['out_file','out_file2'],
                function=mastertransform
            ),
            iterfield=['transform1','transform2'],
            name='mastertransform'
        )

        # transform the tcat image into the atlas space via the mprage transform
        self.transformtcat2atl = MapNode(
            afni.Allineate(
                args='-master BASE -mast_dxyz 3',
                verbose=True,
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            iterfield=['in_file','in_matrix'],
            name='transformtcat2atl'
        )

        # transform the tcat image into the mpr space via the mprage transform
        self.transformtcat2mpr = MapNode(
            afni.Allineate(
                args='-master BASE',
                verbose=True,
                outputtype='NIFTI_GZ',
                overwrite=True
            ),
            iterfield=['in_file','in_matrix'],
            name='transformtcat2mpr'
        )

        # if the mprage is oblique (it probably is) you have to manually restore the obliquity
        # becaue 3dAllineate (and many AFNI tools) set the image to Plumb even if it isn't
        self.prermoblique = Node(
            Merge(
                in2='IJK_TO_DICOM_REAL'
            ),
            name='prermoblique'
        )
        self.remakeoblique = MapNode(
            afni.Refit(),
            iterfield=['in_file'],
            name='remakeoblique'
        )

        # deoblique the MASTEREPIREF and compute the transform between EPIREF and MASTEREPIREF obliquity
        self.deobliquemasterepiref = MapNode(
            Function(
                input_names=['in_file','card2oblique'],
                output_names=['out_file','ob_transform'],
                function=warp_custom
            ),
            iterfield=['in_file','card2oblique'],
            name='deobliquemasterepiref'
        )

        # resample the EPIREF to the MASTEREPIREF grid
        self.resampleepiref2masterepiref = MapNode(
            afni.Resample(
                outputtype='NIFTI_GZ',
                resample_mode='Cu'
            ),
            iterfield=['in_file','master'],
            name='resampleepiref2masterepiref'
        )

        # register the MASTER to the EPIREF
        self.registermaster2epiref = MapNode(
            afni.Allineate(
                args='-nocmass -source_automask -master SOURCE',
                verbose=True,
                warp_type='shift_rotate',
                two_pass=True,
                two_best=11,
                autoweight='',
                cost='nmi',
                out_matrix='EPI1_e2a_only_mat.aff12.1D',
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','reference'],
            name='registermaster2epiref'
        )

        # TRANSFORM rawEPI into ATL space
        # concatenate MPR-ATL -I, OBMPR-OBEPI, and MPR-EPI -I into a master transform
        self.transformrawEPI2ATL = MapNode(
            Function(
                input_names=['in_file','tfm1','tfm2','tfm3','tfm4'],
                output_names=['master_transform'],
                function=concattransform
            ),
            iterfield=['tfm1','tfm2','tfm3','tfm4'],
            name='transformrawEPI2ATL'
        )

        # transform the tcat image into the atlas space via the mprage-EPI1 transform
        self.transformtcat2mprageepi = MapNode(
            afni.Allineate(
                args='-master BASE -mast_dxyz 3',
                verbose=True,
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','in_matrix'],
            name='transformtcat2mprageepi'
        )

        # TRANSFORM rawEPI into EPI1 space
        self.transformrawEPI2EPI1 = MapNode(
            Function(
                input_names=['tfm1','tfm2'],
                output_names=['master_transform'],
                function=concattransform2
            ),
            iterfield=['tfm1','tfm2'],
            name='transformrawEPI2EPI1'
        )

        # transform the tcat image into the EPI1 space
        self.transformtcat2epi1 = MapNode(
            afni.Allineate(
                args='-master BASE',
                verbose=True,
                overwrite=True,
                outputtype='NIFTI_GZ'
            ),
            iterfield=['in_file','in_matrix','reference'],
            name='transformtcat2epi1'
        )

        # if the mprage is oblique (it probably is) you have to manually restore the obliquity
        # it would be nice if 3dAllineate didn't set this to Plumb by default
        self.brikconvert = MapNode( # convert to AFNI because the atrcopy doesn't work in nifti mode
            afni.Copy(
                outputtype='AFNI'
            ),
            iterfield=['in_file'],
            name='brikconvert'
        )
        self.prermoblique2 = Node(
            Function(
                input_names=['in1'],
                output_names=['out'],
                function=lambda in1: (in1[0],'IJK_TO_DICOM_REAL')
            ),
            name='prermoblique2'
        )
        self.remakeoblique2 = MapNode(
            afni.Refit(),
            iterfield=['in_file'],
            name='remakeoblique2'
        )

        # there are 3 ways to bring rawEPI into the ATLAS space (all need volreg, epi-mpr, and mpr-atl:
        # use the volreg results with EPI1 as the referent, and the epi-mpr transform for EPI1
        # use the volreg results with INT  as the referent, and the epi-mpr transform for EPI1
        # use the volreg results with INT  as the referent, and the epi-mpr tranfrorm for EPIX
        #
        # only the first and second options will enforce cross-run alignment

        # for run 1, all methods are the same


        # Output
        self.output = []
        for n in range(4):
            self.output.append(Node(
                DataSink(
                    base_directory=self.BASE_DIR,
                    substitutions=[
                        ('_subject_id_',''),
                        ('_calc_calc_calc_calc_calc','')
                    ]
                ),
                name='output_{}'.format(n)
            ))
