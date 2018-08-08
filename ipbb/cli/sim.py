from __future__ import print_function
# ------------------------------------------------------------------------------

# Modules
import click
import os
import ipbb
import subprocess
import sys
import sh
import shutil
import tempfile
import getpass

# Elements
from os.path import join, splitext, split, exists, splitext, basename, dirname, abspath, expandvars
from click import echo, secho, style, confirm

# Tools imports
from .utils import DirSentry, ensureNoMissingFiles, echoVivadoConsoleError, getClickRootName
from ..tools.common import which, mkdir, SmartOpen

# DepParser imports
from ..depparser.IPCoresSimMaker import IPCoresSimMaker
from ..depparser.SimlibMaker import SimlibMaker
from ..depparser.ModelSimProjectMaker import ModelSimProjectMaker

# 
from ..tools.xilinx import VivadoOpen, VivadoConsoleError
from ..tools.mentor import ModelSimBatch, ModelSimBatch, autodetect


kIPExportDir = 'ipcores_sim'

# ------------------------------------------------
class ModelsimNotFoundError(Exception):

    def __init__(self, message):
        # Call the base class constructor with the parameters it needs
        super(ModelsimNotFoundError, self).__init__(message)
# ------------------------------------------------


# ------------------------------------------------------------------------------
def ensureModelsim(env):
    '''Utility function ensuring that the simulation environment is correctly setup'''
    if env.currentproj.config['toolset'] != 'sim':
        raise click.ClickException(
            "Work area toolset mismatch. Expected 'sim', found '%s'" % env.currentproj.config['toolset'])

    # -------------------------------------------------------------------------
    if not which('vsim'):
        raise click.ClickException(
            'Failed to detect Modelsim/Questa simulation environment. Is the environment setup correctly?')
# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
@click.group('sim', short_help="Set up simulation projects.", chain=True)
@click.pass_context
@click.option('-p', '--proj', metavar='<name>', default=None, help='Switch to <name> before running subcommands.')
def sim(ctx, proj):
    '''Simulation commands'''

    env = ctx.obj

    if proj is not None:

        # Change directory before executing subcommand
        from .proj import cd
        ctx.invoke(cd, projname=proj)
        return
    else:
        if env.currentproj.name is None:
            raise click.ClickException('Project area not defined. Move to a project area and try again')

    ensureModelsim(env)
    # -------------------------------------------------------------------------
# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
@sim.command('setup-simlib', short_help="Compile xilinx simulation libraries")
@click.option('-x', '--xilinx-simlib', 'aXilSimLibsPath', default=join('${HOME}', '.xilinx_sim_libs'), envvar='IPBB_SIMLIB_BASE', metavar='<path>', help='Xilinx simulation library target directory. The default value is overridden by IPBB_SIMLIB_BASE environment variable when defined', show_default=True)
@click.option('-f', '--force', 'aForce', is_flag=True, help="Force simlib compilation/check.")
@click.option('-s', '--to-script', 'aToScript', default=None, help="Write Vivado tcl script to file and exit (dry run).")
@click.option('-o', '--to-stdout', 'aToStdout', is_flag=True, help="Print Vivado tcl commands to screen (dry run).")
@click.pass_obj
def setupsimlib(env, aXilSimLibsPath, aToScript, aToStdout, aForce):
    lSessionId = 'setup-simlib'

    # -------------------------------------------------------------------------
    if not which('vivado'):
        # if 'XILINX_VIVADO' not in os.environ:
        raise click.ClickException(
            'Vivado is not available. Have you sourced the environment script?')
    # -------------------------------------------------------------------------

    lDryRun = aToScript or aToStdout

    # Use compiler executable to detect Modelsim's flavour
    lSimVariant = autodetect()

    # For questa and modelsim the simulator name is the variant name in lowercase
    lSimulator = lSimVariant.lower()
    echo(style(lSimVariant, fg='blue')+" detected")

    lDepFileParser = env.depParser

    # Guess the current vivado version from environment
    lVivadoVersion = basename(os.environ['XILINX_VIVADO'])
    secho('Using Vivado version: '+lVivadoVersion, fg='green')

    # -------------------------------------------------------------------------
    # Store the target path in the env, for it to be retrieved by Vivado
    # i.e. .xilinx_sim_libs/2017.4
    lSimlibPath = expandvars(join(aXilSimLibsPath, lVivadoVersion))

    echo ("Using Xilinx simulation library path: " + style(lSimlibPath, fg='blue'))

    lCompileSimlib = not exists(lSimlibPath) or aForce

    if not lCompileSimlib:
        echo("Xilinx simulation library exist at {}. Compilation will be skipped.".format(lSimlibPath))
    else:
        echo("Xilinx simulation library will be generated at {}".format(style(lSimlibPath, fg='blue')))

        lSimlibMaker = SimlibMaker(lSimulator, lSimlibPath)
        try:
            with (
                # Pipe commands to Vivado console
                VivadoOpen(lSessionId) if not lDryRun 
                else SmartOpen(
                    # Dump to script
                    aToScript if not aToStdout 
                    # Dump to terminal
                    else None
                )
            ) as lVivadoConsole:

                lSimlibMaker.write(
                    lVivadoConsole
                )        

        except VivadoConsoleError as lExc:
            echoVivadoConsoleError(lExc)
            raise click.Abort()
        except RuntimeError as lExc:
            secho("Error caught while generating Vivado TCL commands:\n" +
                  "\n".join(lExc), fg='red'
                  )
            raise click.Abort()
    shutil.copy(join(lSimlibPath, 'modelsim.ini'), '.')

# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
@sim.command('ipcores', short_help="Generate vivado sim cores for the current design.")
@click.option('-x', '--xilinx-simlib', 'aXilSimLibsPath', default=join('${HOME}', '.xilinx_sim_libs'), envvar='IPBB_SIMLIB_BASE', metavar='<path>', help='Xilinx simulation library target directory. The default value is overridden by IPBB_SIMLIB_BASE environment variable when defined', show_default=True)
@click.option('-s', '--to-script', 'aToScript', default=None, help="Write Vivado tcl script to file and exit (dry run).")
@click.option('-o', '--to-stdout', 'aToStdout', is_flag=True, help="Print Vivado tcl commands to screen (dry run).")
@click.pass_obj
def ipcores(env, aXilSimLibsPath, aToScript, aToStdout):
    '''
    Generate the vivado libraries and cores required to simulate the current design.

    '''
    lSessionId = 'ipcores'
    lIpCoresModelsimIni = 'modelsim.ipcores.ini'

    # -------------------------------------------------------------------------
    if not which('vivado'):
        # if 'XILINX_VIVADO' not in os.environ:
        raise click.ClickException(
            'Vivado is not available. Have you sourced the environment script?')
    # -------------------------------------------------------------------------

    lDryRun = aToScript or aToStdout

    # Use compiler executable to detect Modelsim's flavour
    lSimVariant = autodetect()

    # For questa and modelsim the simulator name is the variant name in lowercase
    lSimulator = lSimVariant.lower()
    echo(style(lSimVariant, fg='blue')+" detected")

    lDepFileParser = env.depParser

    # Guess the current vivado version from environment
    lVivadoVersion = basename(os.environ['XILINX_VIVADO'])
    secho('Using Vivado version: '+lVivadoVersion, fg='green')

    # -------------------------------------------------------------------------
    # Store the target path in the env, for it to be retrieved by Vivado
    # i.e. .xilinx_sim_libs/2017.4
    lSimlibPath = expandvars(join(aXilSimLibsPath, lVivadoVersion))

    echo ("Using Xilinx simulation library path: " + style(lSimlibPath, fg='blue'))

    if not exists(lSimlibPath):
        secho("Warning: Simulation Xilinx libraries not found. Likely this is a problem.\nPlease execute {} sim setup-simlibs to generate them.".format(getClickRootName()), fg='yellow')
        confirm("Do you want to continue anyway?", abort=True)
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Extract the list of cores
    lIPCores = [ 
                split(name)[1] for name, ext in 
                ( splitext(src.FilePath) for src in lDepFileParser.commands["src"] )
                    if ext in [".xci", ".edn"]
                ]

    if not lIPCores:
        secho ("WARNING: No ipcore files detected in this project", fg='yellow')
        return
    else:
        echo ('List of ipcores in project')
        for lIPCore in lIPCores:
            echo('- ' + style(lIPCore, fg='blue'))
    # -------------------------------------------------------------------------

    # For questa and modelsim the simulator name is the variant name in lowercase
    lIPCoreSimMaker = IPCoresSimMaker(lSimlibPath, lSimVariant, lSimulator, kIPExportDir)

    secho("Generating ipcore simulation code", fg='blue')

    try:
        with (
            # Pipe commands to Vivado console
            VivadoOpen(lSessionId) if not lDryRun 
            else SmartOpen(
                # Dump to script
                aToScript if not aToStdout 
                # Dump to terminal
                else None
            )
        ) as lVivadoConsole:
        
            lIPCoreSimMaker.write(
                lVivadoConsole,
                lDepFileParser.vars,
                lDepFileParser.components,
                lDepFileParser.commands,
                lDepFileParser.libs,
                lDepFileParser.maps
            )
    except VivadoConsoleError as lExc:
        echoVivadoConsoleError(lExc)
        raise click.Abort()
    except RuntimeError as lExc:
        secho("Error caught while generating Vivado TCL commands:\n" +
              "\n".join(lExc), fg='red'
              )
        raise click.Abort()

    # Copy the generated modelsim ini file locally, with a new name
    shutil.copy(join(lSimlibPath, 'modelsim.ini'), join(os.getcwd(), lIpCoresModelsimIni))
    secho("Imported modelsim.ini from {} to {}".format(lSimlibPath, lIpCoresModelsimIni), fg='blue')

    # Prepare the area where to compile the simulation
    lIPSimDir = join(kIPExportDir,lSimulator)
    # Create the target directory for the code simulation
    mkdir(join(lIPSimDir, '{0}_lib'.format(lSimulator), 'work'))
    # and copy the simlibrary config file into it
    shutil.copy(join(lSimlibPath, 'modelsim.ini'), lIPSimDir)

    # Compile 
    secho("Compiling ipcore simulation", fg='blue')

    with ModelSimBatch(echo=aToStdout, dryrun=lDryRun, cwd=lIPSimDir) as lSim:
        lSim('do compile.do')
    

    # ----------------------------------------------------------
    # Collect the list of libraries generated by ipcores to add them to
    # modelsim.ini
    lVivadoYear = [int(v) for v in lVivadoVersion.split('.')]
    
    if lVivadoYear[0] >= 2017:
        # Vivado 2017 requires an additional folder on the simulation path
        lCoreSimDir = abspath(join(
                kIPExportDir, 
                lSimulator,
                '{0}_lib'.format(lSimulator),
                'msim'
            ))
    else:
        # Vivado 2016<
        lCoreSimDir = abspath(join(
                kIPExportDir, 
                lSimulator,
                'msim'
            ))

    if not exists( lCoreSimDir ):
        raise click.ClickException("Simlib directory not found")

    lSimLibs = next(os.walk(lCoreSimDir))[1]
    echo ('Detected simulation libraries: '+ style(', '.join(lSimLibs), fg='blue'))

    # add newly generated libraries to modelsim.ini
    echo ('Adding generated simulation libraries to modelsim.ini')
    import ConfigParser

    lModelsimIni = ConfigParser.RawConfigParser()
    lModelsimIni.read('modelsim.ipcores.ini')
    for lSimLib in lSimLibs:
        echo (' - ' + lSimLib)
        lModelsimIni.set('Library', lSimLib, join(lCoreSimDir, lSimLib))

    lLibSearchPaths = lModelsimIni.get('vsim', 'librarysearchpath').split() if  lModelsimIni.has_option('vsim', 'librarysearchpath') else []

    lLibSearchPaths += lSimLibs

    lNoDups = []
    for lSimLib in lLibSearchPaths:
        if lSimLib in lNoDups:
            continue
        lNoDups.append(lSimLib)

    lModelsimIni.set('vsim', 'librarysearchpath', ' '.join(lNoDups))

    # Make a backup copy of modelsim.ini (generated by ipcores)
    with SmartOpen('modelsim.ini') as newIni:
        lModelsimIni.write(newIni.target)
# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
@sim.command()
@click.option('--dev', metavar='DEVICE', default='tap0', help='new virtual device')
@click.option('--ipbuspkg', metavar='IPBUSPACKAGE', default='ipbus-firmware', help='ipbus firmware package')
@click.pass_obj
def fli(env, dev, ipbuspkg):
    """
    Build the Modelsim-ipbus foreign language interface
    """

    # -------------------------------------------------------------------------
    # Must be in a build area
    if env.currentproj.name is None:
        raise click.ClickException(
            'Project area not defined. Move into a project area and try again')

    if env.currentproj.config['toolset'] != 'sim':
        raise click.ClickException(
            "Work area toolset mismatch. Expected 'sim', found '%s'" % env.currentproj.config['toolset'])
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    if not which('vsim'):
        raise click.ClickException(
            "ModelSim is not available. Have you sourced the environment script?")
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    if ipbuspkg not in env.sources:
        raise click.ClickException(
            "Package %s not found in source/. The FLI cannot be built." % ipbuspkg)
    # -------------------------------------------------------------------------

    # Set ModelSim root based on vsim's path
    os.environ['MODELSIM_ROOT'] = (dirname(dirname(which('vsim'))))
    # Apply set
    # os.environ['MTI_VCO_MODE']='64'

    lFliSrc = join(env.srcdir, ipbuspkg, 'components', 'ipbus_eth',
                   'firmware', 'sim', 'modelsim_fli')

    import sh
    # Clean-up
    sh.rm('-rf', 'modelsim_fli', 'mac_fli.so', _out=sys.stdout)
    # Copy
    sh.cp('-a', lFliSrc, './', _out=sys.stdout)
    # Make
    sh.make('-C', 'modelsim_fli', 'TAP_DEV={0}'.format(dev), _out=sys.stdout)
    # Link
    sh.ln('-s', 'modelsim_fli/mac_fli.so', '.', _out=sys.stdout)

# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
@sim.command('make-project', short_help="Assemble the simulation project from sources")
@click.option('-r/-n', '--reverse/--natural', 'aReverse', default=True)
@click.option('-o/-1', '--optimize/--single', 'aOptimise', default=True, help="Toggle sim script optimisation.")
@click.option('-s', '--to-script', 'aToScript', default=None, help="Write Modelsim tcl script to file and exit (dry run).")
@click.option('-o', '--to-stdout', 'aToStdout', is_flag=True, help="Print Modelsim tcl commands to screen and exit (dry run).")
@click.pass_obj
def makeproject(env, aReverse, aOptimise, aToScript, aToStdout):
    """
    """

    lSessionId = 'project'

    # -------------------------------------------------------------------------
    # Must be in a build area
    if env.currentproj.name is None:
        raise click.ClickException(
            'Project area not defined. Move into a project area and try again')

    if env.currentproj.config['toolset'] != 'sim':
        raise click.ClickException(
            "Project area toolset mismatch. Expected 'sim', found '%s'" % env.currentproj.config['toolset'])
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    if not which('vsim'):
        raise click.ClickException(
            'ModelSim (vsim) not found. Please add Modelsim to PATH and execute the command again.')
    # -------------------------------------------------------------------------

    # Use compiler executable to detect Modelsim's flavour
    lSimulator = autodetect().lower()

    lDepFileParser = env.depParser

    # Ensure thay all dependencies have been resolved
    ensureNoMissingFiles(env.currentproj.name, lDepFileParser)

    lSimProjMaker = ModelSimProjectMaker(aReverse, aOptimise)

    lDryRun = aToStdout or aToScript
    
    if not lDryRun:
        sh.rm('-rf', 'work')

    try:
        with ModelSimBatch(aToScript, echo=aToStdout, dryrun=lDryRun) as lSim:
            lSimProjMaker.write(
                lSim,
                lDepFileParser.vars,
                lDepFileParser.components,
                lDepFileParser.commands,
                lDepFileParser.libs,
                lDepFileParser.maps
            )
    except sh.ErrorReturnCode as e:
        secho('ERROR: Sim exit code: {}.\nCommand:\n\n   {}\n'.format(e.exit_code,e.full_cmd), fg='red')
        raise click.ClickException("Compilation failed")
    except Exception as e:
        import traceback, StringIO
        lBuf = StringIO.StringIO()
        traceback.print_exc(file=lBuf)
        secho(lBuf.getvalue(), fg='red')
        raise click.ClickException("Compilation failed")
    
    if lDryRun:
        return
    # ----------------------------------------------------------
    # Create a wrapper to force default bindings at load time
    print ('Writing modelsim wrapper \'./vsim\'')
    with SmartOpen('vsim') as lVsimSh:
        # lVsimSh('#!/bin/sh')
        # lVsimSh('export MTI_VCO_MODE=64')
        # lVsimSh('vsim "$@"')
        lVsimSh('''#!/bin/sh

if [ ! -f modelsim.ini ]; then
    echo "WARNING: modelsim.ini not found. Vivado simulation libraries won't be loaded."
fi

export MTI_VCO_MODE=64
export MODELSIM_DATAPATH="mif/"
vsim "$@"
    ''')

    # Make it executable
    os.chmod('vsim', 0755)
# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
def sim_get_command_aliases(self, ctx, cmd_name):
    """
    Temporary hack for backward compatibility
    """
    rv = click.Group.get_command(self, ctx, cmd_name)
    if rv is not None:
        return rv
    if cmd_name == 'project':
        return click.Group.get_command(self, ctx, 'make-project')

import types
sim.get_command = types.MethodType(sim_get_command_aliases, sim)
# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
@sim.command()
@click.option('--dev', metavar='DEVICE', default='tap0', help='name of the new device')
@click.option('--ip', metavar='IP', default='192.168.201.1', help='ip address of the virtual interface')
@click.pass_obj
def virtualtap(env, dev, ip):
    """VirtualTap
    """

    # -------------------------------------------------------------------------
    if not which('openvpn'):
        raise click.ClickException(
            'OpenVPN (openvpn) not found. Please install it and execute the command again.')
    # -------------------------------------------------------------------------

    lCmds = '''
sudo openvpn --mktun --dev {0}
sudo /sbin/ifconfig {0} up {1}
sudo chmod a+rw /dev/net/tun
'''.format(dev, ip)

    pwd = getpass.getpass("[sudo] password for %s: " % getpass.getuser())
    with sh.contrib.sudo(password=pwd, _with=True):
    # with sh.contrib.sudo( _with=True):
        sh.openvpn('--mktun', '--dev', dev, _out=sys.stdout)
        sh.ifconfig(dev, 'up', ip, _out=sys.stdout)
        sh.chmod('a+rw', '/dev/net/tun', _out=sys.stdout)

# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
@sim.command('mifs')
@click.pass_obj
def mifs(env):

    lDepFileParser = env.depParser

    # print (env.depParser.commands)

    lPaths = []
    for c in env.depParser.commands['src']:
        if splitext(c.FilePath)[1] != '.mif':
            continue
        lPaths.append(c.FilePath)

    if not lPaths:
        return

    sh.mkdir('-p', 'mif')
    for p in lPaths:
        sh.cp(p, 'mif/')
# ------------------------------------------------------------------------------
