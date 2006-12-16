import py
import thread
from zipfile import ZipFile
from cStringIO import StringIO
from pypy.tool.build import build

class PPBClient(object):
    def __init__(self, channel, sysinfo, testing=False):
        self.channel = channel
        self.sysinfo = sysinfo
        self.busy_on = None
        self.refused = []
        self.testing = testing

        from pypy.tool.build import ppbserver
        self.server = ppbserver
        self.server.register(self)
        
    def sit_and_wait(self):
        """connect to the host and wait for commands"""
        self.channel.waitclose()
        self.channel.close()

    def compile(self, request):
        """send a compile job to the client side"""
        self.channel.send(request.serialize())
        accepted = self.channel.receive()
        if accepted:
            self.busy_on = request
            thread.start_new_thread(self.wait_until_done, (request,))
        else:
            self.refused.append(request)
        return accepted

    def wait_until_done(self, request):
        buildpath = self.server.get_new_buildpath(request)
        
        if not self.testing:
            fp = buildpath.zipfile.open('w')
            gotdata = False
            try:
                while True:
                    # read data in chunks
                    try:
                        chunk = self.channel.receive()
                    except EOFError:
                        # stop compilation, client has disconnected
                        return
                    # end of data is marked by sending a None
                    if chunk is None:
                        break
                    gotdata = True
                    fp.write(chunk)
            finally:
                fp.close()
            # write the log (process stdout/stderr) to the buildpath
            buildpath.log = self.channel.receive()

        self.server.compilation_done(buildpath)
        self.busy_on = None

initcode = """
    import sys
    sys.path += %r
    
    from pypy.tool.build.client import PPBClient

    try:
        try:
            client = PPBClient(channel, %r, %r)
            client.sit_and_wait()
        except:
            try:
                import sys, traceback
                exc, e, tb = sys.exc_info()
                channel.send(str(exc) + ' - ' + str(e))
                for line in traceback.format_tb(tb):
                    channel.send(line[:-1])
                del tb
            except:
                pass
    finally:
        channel.close()
"""
def init(gw, sysconfig, path=None, port=12321, testing=False):
    from pypy.tool.build import execnetconference
    from pypy.config.config import make_dict
    
    if path is None:
        path = []

    sysinfo = make_dict(sysconfig)
    conference = execnetconference.conference(gw, port, False)
    channel = conference.remote_exec(initcode % (path, sysinfo, testing))
    return channel

class ChannelWrapper(object):
    """ wrapper around a channel

        implements (a small part of) the file interface, sends the data
        over the wire in chunks, ending with a None
    """
    def __init__(self, channel):
        self.channel = channel
        self.loc = 0

    def write(self, data):
        self.loc += len(data)
        self.channel.send(data)

    def close(self):
        self.channel.send(None)

    def tell(self):
        return self.loc

    def flush(self):
        pass

def zip_result(res_dir, channel):
    channelwrapper = ChannelWrapper(channel)
    zip = ZipFile(channelwrapper, 'w')
    # might not be C pypy...
    # zip.writestr('pypy-c', res_dir.join('testing_1/testing_1').read())
    for fpath in res_dir.visit():
        try:
            zip.writestr(fpath.relto(res_dir), fpath.read())
        except (py.error.ENOENT, py.error.EISDIR), exc:
            print exc
            continue
    zip.close()
    channelwrapper.close()

def tempdir(parent=None):
    i = 0
    if parent is None:
        parent = py.path.local('/tmp')
    while 1:
        dirname = 'buildtemp-%s' % (i,)
        if not parent.join(dirname).check():
            return parent.ensure(dirname, dir=True)
        i += 1

def main(config, path, compilefunc):
    from py.execnet import SshGateway, PopenGateway

    if config.server in ['localhost', '127.0.0.1']:
        gw = PopenGateway()
    else:
        gw = SshGateway(config.server)
        
    channel = init(gw,
                   config.system_config,
                   path=config.path,
                   port=config.port)

    print channel.receive() # welcome message
    try:
        try:
            while 1:
                # receive compile requests
                request = channel.receive()
                if isinstance(request, str):
                    try:
                        request = build.BuildRequest.fromstring(request)
                    except (KeyError, SyntaxError), e:
                        print ('exception occurred when trying to '
                               'interpret the following request:')
                        print request
                        print
                        print 'going to continue'
                        continue
                else:
                    raise ValueError(
                        'received wrong unexpected data of type %s' % (
                                type(request),)
                    )
                accepting = True
                for checker in config.client_checkers:
                    if not checker(request):
                        if hasattr(checker, 'im_func'):
                            name = '%s.%s' % (checker.im_class.__name__,
                                              checker.im_func.func_name)
                        else:
                            name = checker.func_name
                        print 'request refused by checker', name
                        accepting = False
                        break
                channel.send(accepting)
                if not accepting:
                    print 'refusing compilation'
                    continue
                # XXX we should compile here, using data dict for info
                print 'compilation requested for %s' % (request,)

                # subversion checkout
                print 'checking out %s@%s' % (request.svnurl,
                                              request.normalized_rev)
                temp = tempdir()
                svnwc = py.path.svnwc(temp)
                svnwc.checkout(request.svnurl)
                svnwc.update(request.normalized_rev)

                try:
                    print 'starting compilation'
                    upath, log = compilefunc(svnwc, request.compileinfo)
                except KeyboardInterrupt:
                    print 'quitting...'
                    break

                if upath:
                    # send over zip data, end with a None
                    print 'compilation successful, sending to server'
                    zip_result(py.path.local(upath), channel)
                else:
                    print 'compilation failed, notifying server'
                    # just send the None
                    channel.send(None)
                
                # send over logs
                print 'sending log'
                channel.send(log)
                
                print 'done with compilation, waiting for next'
        except EOFError:
            py.std.sys.exit()
    finally:
        channel.close()
        gw.exit()

