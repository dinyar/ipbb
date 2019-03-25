from __future__ import print_function, absolute_import
# ------------------------------------------------------------------------------

import time
import os
import shutil


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class IPCoresSimMaker(object):

    _compiler = 'vcom'

    def __init__(self, aSimlibPath, aSimulator, aExportDir):
        self.simlibPath = aSimlibPath
        self.simulator = aSimulator
        self.exportdir = aExportDir

    @property
    def targetSimulator(self):
        return self.simulator

    def write(self, aTarget, aScriptVariables, aComponentPaths, aCommandList, aLibs):

        write = aTarget

        write('# Autogenerated project build script')
        write(time.strftime('# %c'))
        write()

        lWorkingDir = os.path.abspath(os.path.join(os.getcwd(), 'top'))

        write('set outputDir {0}'.format(lWorkingDir))
        write('file mkdir $outputDir')

        # write('create_project top $outputDir -force'.format(**aScriptVariables))

        write(
            'create_project top $outputDir -part {device_name}{device_package}{device_speed} -force'.format(
                **aScriptVariables
            )
        )

        # Add ip repositories to the project variable
        write('set_property ip_repo_paths {{{}}} [current_project]'.format(
            ' '.join(map( lambda c: c.FilePath, aCommandList['iprepo']))
        )
        )

        write('''
set proj_top [get_projects top]
set_property "default_lib" "xil_defaultlib" $proj_top
set_property "simulator_language" "Mixed" $proj_top
set_property "source_mgmt_mode" "DisplayOnly" $proj_top
set_property "target_language" "VHDL" $proj_top
''')

        write('set_property target_simulator ' + self.targetSimulator + ' [current_project]')

        write(
            'set_property compxlib.{}_compiled_library_dir {} [current_project]'.format(
                self.targetSimulator,
                self.simlibPath
            )
        )

        write()
        lXCIs = []
        # write('set f [open 'xil_ip_compile.tcl' w]' )
        for src in reversed(aCommandList['src']):
            lPath, lBasename = os.path.split(src.FilePath)
            lName, lExt = os.path.splitext(lBasename)

            if lExt in ['.xci', '.edn']:
                write(
                    'import_files -norecurse -fileset sources_1 {0}'.format(src.FilePath))
                if lExt == '.xci':
                    lXCIs.append( (lName, lBasename) )
                #     write('upgrade_ip [get_ips {0}]'.format(lName))
                #     write(
                #         'generate_target simulation [get_files {0}]'.format(lBasename)
                #         )

        if lXCIs:
            lIPs, lIPFiles = zip(*lXCIs)
            write('upgrade_ip [get_ips {0}]'.format(' '.join(lIPs)))

            for lFile in lIPFiles:
                write('generate_target simulation [get_files {0}]'.format(lFile))

            write('set_property top top [get_filesets sim_1]')
            write('export_simulation -force -simulator {} -directory {} -lib_map_path {}'.format(self.targetSimulator, self.exportdir, self.simlibPath))

# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
