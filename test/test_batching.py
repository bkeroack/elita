__author__ = 'bkeroack'

import elita.deployment.deploy

import pprint
pp = pprint.PrettyPrinter(indent=4)

divisor = 2

rolling_groups = {
    "group0":
    {
        "servers": ["server0", "server1", "server2", "server3"],
        "gitdeploys": ["gd0", "gd1"]
    },
    "group1":
    {
        "servers": ["server4", "server5", "server6", "server7"],
        "gitdeploys": ["gd0", "gd2"]
    }
}

nonrolling_groups = {
        "group2":
        {
            "servers": ["server8", "server9"],
            "gitdeploys": ["gd0", "gd3"]
        }
}

ordered_groups = {
    "group3":
        {
            "servers": ["server10", "server11"],
            "gitdeploys": [["gd9"], ["gd4"]]
        },
    "group4":
        {
            "servers": ["server12", "server13"],
            "gitdeploys": [["gd9"], ["gd5"]]
        }
}

simulated_scorebig_rolling_groups = {
    "ConsumerWebApp": {
        "servers": ["consumer0", "consumer1"],
        "gitdeploys": [["Configs"], ["Consumer"]]
    },
    "ExtranetWebApp": {
        "servers": ["extranet0", "extranet1"],
        "gitdeploys": [["Configs"], ["Extranet"]]
    }
}

simulated_scorebig_nonrolling_groups = {
    "ServiceBusLowApplication": {
        "servers": ["sbl0", "sbl1"],
        "gitdeploys": [["Configs"], ["ServiceBusLow"]]
    },
    "ServiceBusHighApplication": {
        "servers": ["sbh0", "sbh1"],
        "gitdeploys": [["Configs"], ["ServiceBusHigh"]]
    }
}

def generate_server_batch_mapping(batches):
    server_batch_mapping = dict()
    for i, b in enumerate(batches):
        for s in b['servers']:
            for group in ordered_groups:
                if s in ordered_groups[group]['servers']:
                    for g in b['gitdeploys']:
                        if s in server_batch_mapping:
                            server_batch_mapping[s][g] = i
                        else:
                            server_batch_mapping[s] = {g: i}
    return server_batch_mapping

def test_rolling_batches():
    '''
    Test that rolling groups are split up into the requested batches
    '''

    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, rolling_groups, None)

    assert len(batches) == 2
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert all([len(x['servers']) == 4 for x in batches])
    assert sorted(batches[0]['servers']) == sorted(['server0', 'server1', 'server4', 'server5'])
    assert sorted(batches[1]['servers']) == sorted(['server2', 'server3', 'server6', 'server7'])
    assert all([sorted(x['gitdeploys']) == sorted(['gd0', 'gd1', 'gd2']) for x in batches])
    assert not any([x['ordered_gitdeploy'] for x in batches])


def test_rolling_and_nonrolling_batches():
    '''
    Test that simultaneous rolling and non-rolling groups are split into appropriate batches
    '''

    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, rolling_groups, nonrolling_groups)

    assert len(batches) == 2
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert len(batches[0]['servers']) == 6
    assert len(batches[1]['servers']) == 4
    assert sorted(batches[0]['servers']) == sorted(['server0', 'server1', 'server4', 'server5', 'server8', 'server9'])
    assert sorted(batches[1]['servers']) == sorted(['server2', 'server3', 'server6', 'server7'])
    assert sorted(batches[0]['gitdeploys']) == sorted(['gd0', 'gd1', 'gd2', 'gd3'])
    assert sorted(batches[1]['gitdeploys']) == sorted(['gd0', 'gd1', 'gd2'])
    assert not any([x['ordered_gitdeploy'] for x in batches])

def test_ordered_rolling_batches():
    '''
    Test that ordered rolling groups are split into batches respecting the ordering
    '''

    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, ordered_groups, None)

    assert len(batches) == 4
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert all([len(x['servers']) == 2 for x in batches])
    assert all([batches[x]['gitdeploys'] == ['gd9'] for x in (0, 2)])
    assert all([sorted(batches[x]['gitdeploys']) == sorted(['gd4', 'gd5']) for x in (1, 3)])
    assert all([sorted(batches[x]['servers']) == sorted(['server12', 'server10']) for x in (0, 1)])
    assert all([sorted(batches[x]['servers']) == sorted(['server11', 'server13']) for x in (2, 3)])
    assert all([x['ordered_gitdeploy'] for x in batches[0::2]])
    assert not any([x['ordered_gitdeploy'] for x in batches[1::2]])


def test_ordered_and_unordered_rolling_batches():
    '''
    Test that simultaneous ordered and unordered rolling groups are split into batches respecting ordering
    '''

    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, dict(ordered_groups,
                                                                                         **rolling_groups), None)

    assert len(batches) == 4
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert not any([x['ordered_gitdeploy'] for x in batches])

    server_batch_mapping = generate_server_batch_mapping(batches)
    for s in server_batch_mapping:
        if 'gd4' in server_batch_mapping[s]:
            assert server_batch_mapping[s]['gd9'] < server_batch_mapping[s]['gd4']
        elif 'gd5' in server_batch_mapping[s]:
            assert server_batch_mapping[s]['gd9'] < server_batch_mapping[s]['gd5']

def test_simulated_scorebig_mixed_groups():
    '''
    Test that ordered and unordered groups similar to ScoreBig setup are split into batches respecting ordering
    '''
    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, simulated_scorebig_rolling_groups,
                                                                           simulated_scorebig_nonrolling_groups)

    assert len(batches) == 4
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert all([x['ordered_gitdeploy'] for x in batches[0::2]])
    assert not any([x['ordered_gitdeploy'] for x in batches[1::2]])

    server_batch_mapping = generate_server_batch_mapping(batches)
    for s in server_batch_mapping:
        if 'Consumer' in server_batch_mapping[s]:
            assert server_batch_mapping[s]['Configs'] < server_batch_mapping[s]['Consumer']
        elif 'ServiceBusLow' in server_batch_mapping[s]:
            assert server_batch_mapping[s]['Configs'] < server_batch_mapping[s]['ServiceBusLow']

def test_simulated_scorebig_unordered_groups():
    '''
    Test that unordered groups similar to ScoreBig setup are split into batches respecting gitdeploy ordering
    '''
    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, None,
                                                                           simulated_scorebig_nonrolling_groups)

    assert len(batches) == 2
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert batches[0]['ordered_gitdeploy'] and not batches[1]['ordered_gitdeploy']

    server_batch_mapping = generate_server_batch_mapping(batches)
    for s in server_batch_mapping:
        if 'ServiceBusHigh' in server_batch_mapping[s]:
            assert server_batch_mapping[s]['Configs'] < server_batch_mapping[s]['ServiceBusHigh']
        elif 'ServiceBusLow' in server_batch_mapping[s]:
            assert server_batch_mapping[s]['Configs'] < server_batch_mapping[s]['ServiceBusLow']



if __name__ == '__main__':
    test_rolling_batches()
    test_rolling_and_nonrolling_batches()
    test_ordered_rolling_batches()
    test_ordered_and_unordered_rolling_batches()