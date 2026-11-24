public class Demo
{
    void chain()
    {
        long followUpDelay = scheduling.getJsonNumber(AbstractSchedulingService.FOLLOW_UP_DELAY_KEY_THAT_IS_MUCH_LONGER_THAN_BEFORE)
                                       .longValue();
        long followUpDelay = scheduling.getJsonNumber(AbstractSchedulingService.FOLLOW_UP_DELAY_KEY_THAT_IS_MUCH_LONGER_THAN_BEFORE,
                                                      someOtherParameter)
                                       .longValue();
        long followUpDelay = scheduling.getJsonNumber(someOtherParameter,
                                                      AbstractSchedulingService.FOLLOW_UP_DELAY_KEY_THAT_IS_MUCH_LONGER_THAN_BEFORE)
                                       .longValue();
    }

    void plainCall()
    {
        assertEquals(keySingle, keyDouble,
                     "Single-source and two-source constructors should produce equal keys");
        if (failed) {
            throw new IllegalStateException("Replicator failed to become idle after 20 seconds, aborting....");
        }
    }

    void fitsOnItsOwnRow()
    {
        doSomethingWithAValue(
            AbstractSchedulingService.FOLLOW_UP_DELAY_KEY_A_BIT_LONGER);
    }
}
