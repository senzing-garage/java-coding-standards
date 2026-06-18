public class Demo
{
    public void runWithVeryLongMethodName()
    {
        String result = thisIsAReallyLongVariableName.method(
            longArgumentNameOne,
            longArgumentNameTwoo,
            longArgumentNameThree)
                                                     .chainMethodB()
                                                     .chainMethodC()
                                                     .toString();
    }
}
