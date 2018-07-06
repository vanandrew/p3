"""Define Nodes for nipype workflow

TODO

"""
import os
import inspect
from nipype import Workflow
from nipype import Node
from nipype.interfaces.utility import IdentityInterface
from nipype.interfaces.io import DataSink

def generate_subworkflows(imported_workflows,settings):
    """
        TODO: document this function
    """

    # create sub-workflows
    subworkflows = {}
    # loop over all imported workflows

    for name,wf in imported_workflows.items():
        # find the class whos base is the workflowgenerator
        for obj in dir(wf):
            if inspect.isclass(getattr(wf,obj)): # check if object is class
                # the object is a workflowgenerator object
                if getattr(wf,obj).__bases__[0] == workflowgenerator:
                    # create and assign the workflow to the dictionary
                    subworkflows[name] = getattr(wf,obj)(name,settings)

    # return subworkflows
    return subworkflows

def generate_connections(subworkflows,settings):
    """
        TODO: document this function
    """

    # define initial connection list
    connections = []

    # go through connections in settings and build connections list
    for connection_entry in settings['connections']:
        # append to connections list
        connections.append(( # define tuple
            subworkflows[connection_entry['source']],
            subworkflows[connection_entry['destination']],
            [tuple(link) for link in connection_entry['links']] # convert each entry in links list to tuple
        ))

    # return connection list
    return connections

def default_settings():
    """
        TODO: document this function
    """

    # define default settings
    settings = {}
    settings['epi_reference'] = 4 # selects the epi reference frame to use (It is 0 indexed.)
    settings['T1_reference'] = 0 # selects the T1 to align to if multiple T1 images in dataset (It is 0 indexed. T1s are order from lowest session,lowest run to highest session,highest run. Leave as 0 if only 1 T1)
    settings['brain_radius'] = 50 # set brain radius for FD calculation (in mm)
    settings['nonlinear_atlas'] = True # do nonlinear transform for atlas alignment using 3dQwarp
    settings['atlas'] = 'TT_N27+tlrc' # sets the atlas align target (you can use `cat ${AFNI_DIR}/AFNI_atlas_spaces.niml` (where ${AFNI_DIR} is your afni directory) to show availiable atlas align targets)
    settings['avgT1s'] = True # avgs all T1s in dataset if multiple T1s (Set this to False if you only have 1 T1 or you will probably get an error!)
    settings['field_map_correction'] = False # sets whether pipeline should run field map correction. You should have field maps in your dataset for this to work.
    settings['slice_time_correction'] = True # sets whether epi images should be slice time corrected
    settings['despiking'] = True # sets whether epi images should be despiked
    settings['run_recon_all'] = False # sets whether pipeline should run recon-all (if you decide not to you should place your own freesurfer data under output freesurfer_output, where each folder is {NAME} in sub-{NAME} in the bids dataset)
    settings['workflows'] = [ # defines the workflows to import
            'bidsselector',
            'freesurfer',
            'skullstrip',
            'timeshiftanddespike',
            'alignt1toatlas',
            'alignboldtot1',
            'alignboldtoatlas'
        ]
    settings['connections'] = [ # defines the input/output connections between workflows
        {
            'source': 'bidsselector',
            'destination': 'freesurfer',
            'links': [
                ['output.T1','input.T1'],
                ['output.subject','input.subject']
            ]
        },
        {
            'source': 'bidsselector',
            'destination': 'skullstrip',
            'links': [
                ['output.T1','input.T1']
            ]
        },
        {
            'source': 'freesurfer',
            'destination': 'skullstrip',
            'links': [
                ['output.orig','input.orig'],
                ['output.brainmask','input.brainmask']
            ]
        },
        {
            'source': 'bidsselector',
            'destination': 'timeshiftanddespike',
            'links': [
                ['output.epi','input.epi']
            ]
        },
        {
            'source': 'skullstrip',
            'destination': 'alignt1toatlas',
            'links': [
                ['output.T1_skullstrip','input.T1_skullstrip']
            ]
        },
        {
            'source': 'timeshiftanddespike',
            'destination': 'alignboldtot1',
            'links': [
                ['output.refimg','input.refimg']
            ]
        },
        {
            'source': 'alignt1toatlas',
            'destination': 'alignboldtot1',
            'links': [
                ['output.T1_0','input.T1_0']
            ]
        },
        {
            'source': 'alignt1toatlas',
            'destination': 'alignboldtoatlas',
            'links': [
                ['output.noskull_at','input.noskull_at'],
                ['output.nonlin_warp','input.nonlin_warp']
            ]
        },
        {
            'source': 'alignboldtot1',
            'destination': 'alignboldtoatlas',
            'links': [
                ['output.oblique_transform','input.oblique_transform'],
                ['output.t1_2_epi','input.t1_2_epi']
            ]
        },
        {
            'source': 'timeshiftanddespike',
            'destination': 'alignboldtoatlas',
            'links': [
                ['output.epi2epi1','input.epi2epi1'],
                ['output.tcat','input.tcat'],
            ]
        }
    ]

    # return settings
    return settings

class basenodedefs:
    """Base class for initializing nodes in workflow

        TODO

    """
    def __init__(self,settings):
        # Define datasink node
        self.datasink = Node(
            DataSink(
                base_directory=os.path.join(settings['output_dir']),
                substitutions=[
                    ('_subject_','sub-')
                ]
            ),
            name='datasink'
        )

    def set_input(self,input_list):
        # assign input list to inputnode fields
        self.inputnode = Node(
            IdentityInterface(
                fields=input_list
            ),
            name='input'
        )

    def set_output(self,output_list):
        # assign output list to outputnode fields
        self.outputnode = Node(
            IdentityInterface(
                fields=output_list
            ),
            name='output'
        )

    def set_subs(self,sub_list):
        # append substitution list to substitutions
        self.datasink.inputs.substitutions.extend(sub_list)

    def set_resubs(self,sub_list):
        # add regular expression substitution to list
        self.datasink.inputs.regexp_substitutions = sub_list

class workflowgenerator:
    """ Base class defining a workflow

        TODO

    """
    def __new__(cls,name,settings):
        # define workflow name and path
        cls.workflow = Workflow(name=name,base_dir=settings['tmp_dir'])
