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
            "gitdeploys": [["gd0"], ["gd4"]]
        },
    "group4":
        {
            "servers": ["server12", "server13"],
            "gitdeploys": [["gd0"], ["gd5"]]
        }
}

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

def test_ordered_rolling_batches():
    '''
    Test that ordered rolling groups are split into batches respecting the ordering
    '''

    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, ordered_groups, None)

    assert len(batches) == 4
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    assert all([len(x['servers']) == 2 for x in batches])
    assert all([batches[x]['gitdeploys'] == ['gd0'] for x in (0, 2)])
    assert all([sorted(batches[x]['gitdeploys']) == sorted(['gd4', 'gd5']) for x in (1, 3)])
    assert all([sorted(batches[x]['servers']) == sorted(['server12', 'server10']) for x in (0, 1)])
    assert all([sorted(batches[x]['servers']) == sorted(['server11', 'server13']) for x in (2, 3)])


def test_ordered_and_unordered_rolling_batches():
    '''
    Test that simultaneous ordered and unordered rolling groups are split into batches respecting ordering
    '''

    batches = elita.deployment.deploy.BatchCompute.compute_rolling_batches(divisor, dict(ordered_groups,
                                                                                         **rolling_groups), None)

    assert len(batches) == 4
    assert all(["servers" in x and "gitdeploys" in x for x in batches])
    #TODO: implement real ordering checks

if __name__ == '__main__':
    test_rolling_batches()
    test_rolling_and_nonrolling_batches()
    test_ordered_rolling_batches()
    test_ordered_and_unordered_rolling_batches()