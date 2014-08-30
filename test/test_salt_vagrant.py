# Tests involving salt that must be run in the Vagrant environment

import salt.client
import multiprocessing

# def run_state_call(target, state, concurrent, q):
#     '''
#     @type q: multiprocessing.Queue
#     '''
#     sc = salt.client.LocalClient()
#     results = list()
#     ret = sc.cmd_iter(target, 'state.sls', [state], kwarg={'concurrent': concurrent})
#     for res in ret:
#         results.append(res)
#     q.put_nowait(results)
#
# def concurrent_state_calls(target, concurrent):
#     q = multiprocessing.Queue()
#     states = ['elita.scorebig.Configs', 'elita.scorebig.Artifacts']
#     results = list()
#     procs = list()
#     for s in states:
#         p = multiprocessing.Process(target=run_state_call, args=(target, s, concurrent, q))
#         p.start()
#         procs.append(p)
#
#     for p in procs:
#         p.join(300)
#
#     for r in q.get_nowait():
#         results.append(r)
#
#     print(results)
#
#
# def test_simultaneous_state_calls_concurrent_false_windows():
#     '''
#     Test simulataneous salt state calls with concurrent flag False
#     '''
#     concurrent_state_calls('web01', False)
#
# def test_simultaneous_state_calls_concurrent_true_windows():
#     '''
#     Test simulataneous salt state calls with concurrent flag True
#     '''
#     concurrent_state_calls('web01', True)
#
# if __name__ == '__main__':
#     test_simultaneous_state_calls_concurrent_false_windows()
#     test_simultaneous_state_calls_concurrent_true_windows()

